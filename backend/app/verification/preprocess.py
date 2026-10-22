"""Pre-processor agent: turn an uploaded PDF or image into clean page images.

Lessons from the sample documents:
- Phone photos are often saved on a tiny PDF page (e.g. 4 x 6 inch) at full camera
  resolution (3694 x 5069 px). Rendering by page size at a fixed DPI shrinks them to
  ~440 px and makes them unreadable, so we take each page's embedded image at its
  native resolution.
- Some PDFs carry a text layer written by a scanner app, and it is wrong. A text
  layer is trusted only when the PDF is born-digital (no page-sized image), and even
  then only as a second signal.
- Files arrive up to ~23 MB; pages are resized to LONG_SIDE px and re-encoded.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps
from pypdf import PdfReader

LONG_SIDE = 2000  # px sent to OCR / the vision model
MIN_LONG_SIDE = 1200  # below this the scan is too small to read reliably
BLUR_THRESHOLD = 60.0  # variance of Laplacian at LONG_SIDE; below = blurry


@dataclass
class PageImage:
    image: Image.Image
    source_px: tuple[int, int]  # resolution before resizing
    blur_score: float
    brightness: float
    quality: float  # 0..1
    issues: list[str] = field(default_factory=list)


@dataclass
class PreprocessResult:
    pages: list[PageImage]
    born_digital: bool
    text_layer: str  # only filled for born-digital PDFs
    issues: list[str] = field(default_factory=list)

    @property
    def quality(self) -> float:
        return min((p.quality for p in self.pages), default=0.0)


def _largest_image(page) -> Image.Image | None:
    best, best_px = None, 0
    try:
        images = list(page.images)
    except Exception:  # malformed image streams: fall back to no image
        return None
    for img in images:
        try:
            pil = img.image
        except Exception:
            continue
        px = pil.width * pil.height
        if px > best_px:
            best, best_px = pil, px
    return best


def _page_covered_by_image(page, img: Image.Image | None) -> bool:
    """A page is a scan when one embedded image is large compared with the page."""
    if img is None:
        return False
    return img.width >= 600 and img.height >= 600


def _quality(img: Image.Image) -> tuple[float, float, float, list[str]]:
    gray = np.asarray(img.convert("L"))
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    issues: list[str] = []
    q = 1.0
    if blur < BLUR_THRESHOLD:
        issues.append("blurry")
        q -= 0.5 * (1 - blur / BLUR_THRESHOLD)
    if brightness < 80:
        issues.append("too dark")
        q -= 0.3
    elif brightness > 245:
        issues.append("washed out")
        q -= 0.3
    return blur, brightness, max(0.0, min(1.0, q)), issues


def _normalise(img: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    img = ImageOps.exif_transpose(img).convert("RGB")
    source = img.size
    scale = LONG_SIDE / max(img.size)
    if scale < 1:
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    return img, source


def _to_page(img: Image.Image) -> PageImage:
    norm, source = _normalise(img)
    blur, brightness, q, issues = _quality(norm)
    if max(source) < MIN_LONG_SIDE:
        issues.append(f"low resolution ({source[0]}x{source[1]} px)")
        q = min(q, 0.6)
    return PageImage(norm, source, blur, brightness, q, issues)


def _render_page(data: bytes, page_no: int, dpi: int = 200) -> Image.Image:
    """Rasterise one page of a born-digital PDF with Poppler (pdftoppm, free)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(data)
        out = Path(tmp) / "page"
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", "-singlefile",
             "-f", str(page_no), "-l", str(page_no), str(src), str(out)],
            check=True, capture_output=True, timeout=60,
        )
        return Image.open(out.with_suffix(".png")).copy()


def preprocess_pdf(data: bytes) -> PreprocessResult:
    reader = PdfReader(io.BytesIO(data))
    pages: list[PageImage] = []
    scanned_pages = 0
    texts: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        img = _largest_image(page)
        if _page_covered_by_image(page, img):
            scanned_pages += 1
            pages.append(_to_page(img))  # native resolution, not page size
        else:
            # Born-digital page: small embedded images are photos or logos, not the page.
            texts.append(page.extract_text() or "")
            pages.append(_to_page(_render_page(data, page_no)))
    born_digital = scanned_pages == 0
    issues = sorted({i for p in pages for i in p.issues})
    text = clean_text("\n".join(texts)) if born_digital else ""
    return PreprocessResult(pages, born_digital, text, issues)


# Government PDFs (e.g. the EWS sample) use non-breaking spaces and soft hyphens:
# "Valid\xa0for\xa0Year\xa02026\xad2027".
_TEXT_FIXES = str.maketrans({"\xa0": " ", "\xad": "-", "–": "-", "—": "-", "​": ""})


def clean_text(text: str) -> str:
    text = text.translate(_TEXT_FIXES)
    return "\n".join(" ".join(line.split()) for line in text.splitlines() if line.strip())


def preprocess_image(data: bytes) -> PreprocessResult:
    img = Image.open(io.BytesIO(data))
    page = _to_page(img)
    return PreprocessResult([page], False, "", page.issues)


def preprocess_file(path: str | Path) -> PreprocessResult:
    path = Path(path)
    data = path.read_bytes()
    if data[:5] == b"%PDF-":
        return preprocess_pdf(data)
    return preprocess_image(data)


def to_jpeg(page: PageImage, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    page.image.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()
