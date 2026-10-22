# AdmitVerify

Internal portal for our NGO counselling team to pre-verify engineering-admission
documents (marksheets, Leaving Certificate, caste, caste validity, NCL, EWS, domicile)
with self-hosted AI agents, and produce one PDF report per student.

Everything is free and open-source and runs on our own server. See the project scope
document for the full design.

## Status

| Part | State |
| --- | --- |
| Verification core (`backend/app/verification`) | Built and tested (42 tests) |
| Pre-processor for uploaded PDFs / photos | Built, tested on all 18 sample documents |
| Document catalog seeded from samples | Built (`data/document_catalog.json`) |
| API (FastAPI), database, invite emails, OTP | Next: Sprint 0 + 1 |
| Web app (Next.js) admin + student portals | Next: Sprint 0 + 1 |
| Extraction agents (vision model + OCR) | Sprint 3 |
| PDF report | Sprint 4 |

## Verification core

```
backend/app/verification/
  preprocess.py   PDF/photo -> clean page images at native resolution; quality score;
                  text layer only from born-digital PDFs
  names.py        order-free name matching (surname-first SSC, "Kumar/Kumari" prefixes,
                  initials, spelling variants); one misread part never counts as a match
  dates.py        every date format seen in the samples, incl. Devanagari digits
  marks.py        PCM / PCB %, best-of-three, group clear, per board (CBSE, HSC, ICSE)
  rules.py        deterministic rules engine -> findings (Blocker / Warning / Info)
  models.py       data passed between agents and rules
  data/document_catalog.json
                  categories, document types, board variants, fields to extract,
                  required documents per category, thresholds (admin-editable seed)
```

Rules implemented: Q1 unreadable field ("not able to read ..., please verify
correctly"), Q2 wrong document, Q3 poor image, C1 required documents, C3 caste on
validity, C7 validity quotes the caste certificate number and date, C8 NCL valid-up-to,
C9 EWS year, C10 category on certificate, E1 E3 E4 E5 E6 eligibility, X1 name across
documents, X2 / X4 date of birth, X5 mother's name.

## Running the tests

Python 3.11+ with `pip install -r backend/requirements.txt`, and `poppler-utils`
installed (`sudo apt install poppler-utils`).

```bash
cd backend
python -m unittest discover -s tests -t . -v
```

To also test against the real sample documents (kept outside Git):

```bash
SAMPLES_DIR="/path/to/Project Document" python -m unittest discover -s tests -t . -v
```

## Sample documents and privacy

The sample documents contain real students' personal data. They are never committed:
`samples/` and `*.pdf` are in `.gitignore`. Test fixtures use invented names and numbers
that copy the layout quirks of the samples.
