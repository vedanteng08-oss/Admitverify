"""Test students modelled on the shared sample documents.

Layouts, field formats, marks patterns and quirks (surname-first SSC, "Kumar"
prefixes, validity quoting the caste certificate, date formats) follow the real
samples. Names and certificate numbers are invented, so no real student data is
stored in the repository.
"""

from app.verification.models import ExtractedDocument, Field, Student


def F(value, conf=0.97, original=None):
    return Field(value=value, confidence=conf, original_text=original)


def student_a_docs() -> dict[str, ExtractedDocument]:
    """OBC student with HSC, SSC, LC, Domicile, caste, validity and NCL (like 'Student A')."""
    return {
        "HSC_MARKSHEET": ExtractedDocument(
            "HSC_MARKSHEET", "HSC_MH",
            fields={
                "name": F("Rohan Vilas Jadhav"),  # HSC: first name first
                "mother_name": F("Sunita"),  # HSC prints first name only
                "seat_no": F("P012345"),
                "exam_month_year": F("FEBRUARY-26"),
                "result": F("PASS"),
            },
            subjects=[
                {"name": "01 ENGLISH", "obtained": 61},
                {"name": "40 MATHEMATICS & STATISTICS", "obtained": 57},
                {"name": "54 PHYSICS", "obtained": 69},
                {"name": "55 CHEMISTRY", "obtained": 76},
                {"name": "97 INFORMATION TECHNOLOGY(SCI)", "obtained": 89},
            ],
        ),
        "SSC_MARKSHEET": ExtractedDocument(
            "SSC_MARKSHEET", "SSC_MH",
            fields={
                "name": F("Jadhav Rohan Vilas"),  # SSC: surname first
                "mother_name": F("Sunita"),
                "result": F("PASS"),
            },
        ),
        "LEAVING_CERT": ExtractedDocument(
            "LEAVING_CERT", "LC",
            fields={"name": F("JADHAV ROHAN VILAS"), "dob": F("01/06/2008")},
        ),
        "DOMICILE": ExtractedDocument(
            "DOMICILE", "AGE_NAT_DOM",
            fields={
                "name": F("Rohan Vilas Jadhav"),
                "dob": F("1st June, 2008 (First of June in the year Two Thousand and Eight)"),
                "certificate_no": F("42100000004"),
                "issue_date": F("24th June, 2026"),
            },
        ),
        "CASTE_CERT": ExtractedDocument(
            "CASTE_CERT", "FORM_8",
            fields={
                "name": F("Kumar Rohan Vilas Jadhav"),
                "father_name": F("Shri Vilas Maruti Jadhav"),
                "caste": F("MALI"),
                "caste_sr_no": F("182"),
                "category": F("Other Backward Class"),
                "certificate_no": F("41900000001"),
                "application_date": F("28/10/2021"),
                "issue_date": F("01/11/2021"),
            },
        ),
        "CASTE_VALIDITY": ExtractedDocument(
            "CASTE_VALIDITY", "BARTI",
            fields={
                "name": F("Rohan Vilas Jadhav"),
                "caste": F("Mali (182)"),
                "category": F("Other Backward Class"),
                "vc_no": F("2025-000000001"),
                "decision_date": F("03/12/2025"),
                "cc_number": F("41900000001"),
                "cc_date": F("01/11/2021"),
            },
        ),
        "NCL": ExtractedDocument(
            "NCL", "FORM_B2",
            fields={
                "name": F("Kumar Rohan Vilas Jadhav"),
                "category": F("Other Backward Class"),
                "certificate_no": F("41900000002"),
                "issue_date": F("20/06/2024"),
                "valid_upto": F("31-Mar- 2027"),
            },
        ),
    }


def student_a() -> Student:
    return Student("AV-2026-000001", "Rohan Vilas Jadhav", "OBC", dob="01-06-2008")


def cbse_hsc() -> ExtractedDocument:
    """CBSE 12th: total = theory + practical, like the CBSE sample."""
    return ExtractedDocument(
        "HSC_MARKSHEET", "CBSE",
        fields={
            "name": F("ANANYA MAHESH KULKARNI"),
            "mother_name": F("MEERA MAHESH KULKARNI"),
            "seat_no": F("15600001"),
            "result": F("PASS"),
        },
        subjects=[
            {"name": "301 ENGLISH CORE", "theory": 71, "practical": 20, "obtained": 91},
            {"name": "041 MATHEMATICS", "theory": 51, "practical": 20, "obtained": 71},
            {"name": "042 PHYSICS", "theory": 40, "practical": 30, "obtained": 70},
            {"name": "043 CHEMISTRY", "theory": 28, "practical": 30, "obtained": 58},
        ],
    )
