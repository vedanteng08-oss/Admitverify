"""Pre-processor tests.

Synthetic tests always run. Tests against the real sample documents run only when
SAMPLES_DIR points at the unzipped 'Project Document' folder; the samples contain
real student data and are never committed to the repository.
"""

import io
import os
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from app.verification.preprocess import LONG_SIDE, preprocess_file, preprocess_image, preprocess_pdf

SAMPLES = Path(os.environ.get("SAMPLES_DIR", "/nonexistent"))


def _text_image(w=1700, h=2200, blur=0) -> Image.Image:
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    for y in range(100, h - 100, 40):
        d.text((100, y), "CASTE CERTIFICATE Outward No 41900000001 " * 3, fill="black")
    return img.filter(ImageFilter.GaussianBlur(blur)) if blur else img


def _as_pdf(img: Image.Image, dpi: float) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PDF", resolution=dpi)
    return buf.getvalue()


class SyntheticTests(unittest.TestCase):
    def test_photo_on_tiny_page_keeps_native_resolution(self):
        # Like the ST samples: 3694x5069 px photo stored on a 4x6 inch page.
        big = _text_image(3694, 5069)
        res = preprocess_pdf(_as_pdf(big, dpi=850))
        page = res.pages[0]
        self.assertEqual(page.source_px, (3694, 5069))
        self.assertEqual(max(page.image.size), LONG_SIDE)
        self.assertFalse(res.born_digital)

    def test_blurry_scan_is_flagged(self):
        sharp = preprocess_image(self._png(_text_image()))
        blurry = preprocess_image(self._png(_text_image(blur=6)))
        self.assertGreater(sharp.quality, blurry.quality)
        self.assertIn("blurry", blurry.issues)

    def test_small_image_is_low_resolution(self):
        res = preprocess_image(self._png(_text_image(500, 700)))
        self.assertTrue(any("low resolution" in i for i in res.issues))

    @staticmethod
    def _png(img):
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()


@unittest.skipUnless(SAMPLES.is_dir(), "set SAMPLES_DIR to run against the real samples")
class SampleDocumentTests(unittest.TestCase):
    def test_every_sample_gives_a_readable_page(self):
        files = sorted(SAMPLES.glob("*/*.pdf"))
        self.assertGreaterEqual(len(files), 18)
        for f in files:
            with self.subTest(file=f.name):
                res = preprocess_file(f)
                self.assertTrue(res.pages)
                self.assertGreaterEqual(max(res.pages[0].image.size), 1200)
                self.assertGreaterEqual(res.quality, 0.6)

    def test_st_photo_is_not_shrunk(self):
        res = preprocess_file(SAMPLES / "Caste Certificate" / "CC_ST.pdf")
        self.assertEqual(res.pages[0].source_px, (3694, 5069))

    def test_scanner_text_layer_is_not_trusted(self):
        res = preprocess_file(SAMPLES / "Caste Validity " / "CV_VJ(A)_NT(B,C,D).pdf")
        self.assertFalse(res.born_digital)
        self.assertEqual(res.text_layer, "")

    def test_born_digital_ews_uses_text_layer(self):
        res = preprocess_file(SAMPLES / "EWS" / "EWS.pdf")
        self.assertTrue(res.born_digital)
        self.assertIn("Certificate No.:", res.text_layer)
        self.assertIn("Valid for Year 2026-2027", res.text_layer)


if __name__ == "__main__":
    unittest.main()
