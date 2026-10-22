"""Tests for the verification core. Run: python -m unittest discover -s tests -v"""

import unittest
from datetime import date

from app.verification.dates import academic_year_covers, parse_date
from app.verification.marks import SubjectMark, compute_eligibility
from app.verification.models import ExtractedDocument, Field, Result, Severity, Student
from app.verification.names import first_name_matches, match_names, normalize
from app.verification.rules import RuleConfig, verify

from .fixtures import F, cbse_hsc, student_a, student_a_docs

CFG = RuleConfig.load()


class NameTests(unittest.TestCase):
    def test_prefixes_removed(self):
        self.assertEqual(normalize("Kumar Rohan Vilas Jadhav"), ["ROHAN", "VILAS", "JADHAV"])
        self.assertEqual(normalize("Shri/Shrimati/Kumari Asha Patil"), ["ASHA", "PATIL"])

    def test_surname_first_matches(self):
        m = match_names("Rohan Vilas Jadhav", "Jadhav Rohan Vilas")
        self.assertEqual(m.verdict, "match")
        self.assertEqual(m.score, 100)

    def test_initial_matches_full_token(self):
        self.assertEqual(match_names("Rohan V. Jadhav", "Rohan Vilas Jadhav").verdict, "match")

    def test_missing_middle_name_is_near_or_match(self):
        self.assertIn(match_names("Rohan Jadhav", "Rohan Vilas Jadhav").verdict, ("match", "near"))

    def test_spelling_variant(self):
        self.assertEqual(match_names("Laxmi Pawar", "Lakshmi Pawar").verdict, "match")

    def test_different_person(self):
        self.assertEqual(match_names("Rohan Vilas Jadhav", "Asha Kiran Patil").verdict, "mismatch")

    def test_scanner_ocr_error_is_near_not_match(self):
        # A scanner text layer in the samples misread "UT" as "W" in a surname.
        m = match_names("KUTARE SAMEER ANIL", "KWARE SAMEER ANIL")
        self.assertNotEqual(m.verdict, "match")

    def test_devanagari_needs_transliteration(self):
        self.assertEqual(match_names("राहुल पाटील", "Rahul Patil").verdict, "unreadable")

    def test_first_name_only(self):
        self.assertTrue(first_name_matches("Sunita Vilas Jadhav", "Sunita"))
        self.assertFalse(first_name_matches("Sunita Vilas Jadhav", "Meera"))


class DateTests(unittest.TestCase):
    def test_formats_from_samples(self):
        cases = {
            "13-05-2026": date(2026, 5, 13),
            "01/11/2021": date(2021, 11, 1),
            "08.07.2008": date(2008, 7, 8),
            "1st June, 2008 (First of June in the year Two Thousand and Eight)": date(2008, 6, 1),
            "28th June, 2026": date(2026, 6, 28),
            "15 Jun 2018": date(2018, 6, 15),
            "31-Mar- 2027": date(2027, 3, 31),
            "31st March 2029": date(2029, 3, 31),
            "2026-06-24 07:57": date(2026, 6, 24),
            "Sun Dec 14 21:52:03 IST 2025": date(2025, 12, 14),
            "दि. २८/०६/२०२६": date(2026, 6, 28),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_date(text).value, expected)

    def test_day_first(self):
        self.assertEqual(parse_date("03/12/2025").value, date(2025, 12, 3))

    def test_invalid(self):
        self.assertFalse(parse_date("31/02/2025").ok)
        self.assertFalse(parse_date("not a date").ok)
        self.assertFalse(parse_date(None).ok)

    def test_academic_year(self):
        self.assertTrue(academic_year_covers("Valid for Year 2026-2027", 2026))
        self.assertTrue(academic_year_covers("(Valid for Year 2026–2027 )", 2026))
        self.assertFalse(academic_year_covers("Valid for Year 2025-2026", 2026))
        self.assertTrue(academic_year_covers("Valid\xa0for\xa0Year\xa02026\xad2027", 2026))

    def test_soft_hyphen_date(self):
        self.assertEqual(parse_date("14\xad06\xad2026").value, date(2026, 6, 14))


class MarksTests(unittest.TestCase):
    def test_hsc_pcm(self):
        r = compute_eligibility("HSC_MH", [
            SubjectMark("40 MATHEMATICS & STATISTICS", 57),
            SubjectMark("54 PHYSICS", 69),
            SubjectMark("55 CHEMISTRY", 76),
            SubjectMark("39 GEOGRAPHY", 84),
        ])
        self.assertEqual(r.pcm_percent, 67.33)
        self.assertTrue(r.group_clear)
        self.assertEqual(r.best_three, ["PHYSICS", "MATHEMATICS", "CHEMISTRY"])

    def test_cbse_theory_plus_practical(self):
        r = compute_eligibility("CBSE", [
            SubjectMark("041 MATHEMATICS", 71, theory=51, practical=20),
            SubjectMark("042 PHYSICS", 70, theory=40, practical=30),
            SubjectMark("043 CHEMISTRY", 58, theory=28, practical=30),
        ])
        self.assertEqual(r.pcm_percent, 66.33)
        self.assertEqual(r.problems, [])

    def test_misread_total_is_flagged(self):
        r = compute_eligibility("CBSE", [
            SubjectMark("MATHEMATICS", 81, theory=51, practical=20),
            SubjectMark("PHYSICS", 70), SubjectMark("CHEMISTRY", 58),
        ])
        self.assertEqual(len(r.problems), 1)

    def test_best_third_subject_is_used(self):
        r = compute_eligibility("HSC_MH", [
            SubjectMark("PHYSICS", 60), SubjectMark("MATHEMATICS", 60),
            SubjectMark("CHEMISTRY", 40), SubjectMark("BIOLOGY", 80),
        ])
        self.assertEqual(r.best_three[-1], "BIOLOGY")
        self.assertEqual(r.pcb_percent, 60.0)

    def test_group_not_clear(self):
        r = compute_eligibility("HSC_MH", [
            SubjectMark("PHYSICS", 30), SubjectMark("MATHEMATICS", 80), SubjectMark("CHEMISTRY", 80),
        ])
        self.assertFalse(r.group_clear)

    def test_missing_maths(self):
        r = compute_eligibility("HSC_MH", [SubjectMark("PHYSICS", 60), SubjectMark("CHEMISTRY", 60)])
        self.assertIn("Mathematics", r.missing)


class RulesEndToEndTests(unittest.TestCase):
    def test_complete_obc_student_is_ready(self):
        res = verify(student_a(), student_a_docs(), CFG)
        failing = [f for f in res.findings if f.result != Result.PASS]
        self.assertEqual(failing, [], [f.message for f in failing])
        self.assertEqual(res.overall_status, "Ready")
        self.assertEqual(res.eligibility["pcm_percent"], 67.33)
        self.assertTrue(res.eligibility["group_clear"])

    def test_missing_document(self):
        docs = student_a_docs()
        del docs["NCL"]
        res = verify(student_a(), docs, CFG)
        (c1,) = res.by_code("C1")
        self.assertEqual(c1.result, Result.FAIL)
        self.assertIn("Non-Creamy Layer", c1.message)
        self.assertEqual(res.overall_status, "Action required")

    def test_unreadable_name_is_flagged_not_guessed(self):
        docs = student_a_docs()
        docs["CASTE_VALIDITY"].fields["name"] = F("Rohan V?l?s", conf=0.4)
        res = verify(student_a(), docs, CFG)
        q1 = [f for f in res.by_code("Q1") if f.evidence.get("field") == "name"]
        self.assertEqual(len(q1), 1)
        self.assertIn("not able to read name, please verify correctly", q1[0].message)
        self.assertEqual(q1[0].result, Result.REVIEW)

    def test_validity_quotes_other_certificate(self):
        docs = student_a_docs()
        docs["CASTE_VALIDITY"].fields["cc_number"] = F("41900009999")
        (c7,) = verify(student_a(), docs, CFG).by_code("C7")
        self.assertEqual(c7.result, Result.FAIL)
        self.assertEqual(c7.severity, Severity.BLOCKER)

    def test_validity_date_differs_is_warning(self):
        docs = student_a_docs()
        docs["CASTE_VALIDITY"].fields["cc_date"] = F("28/10/2021")  # application date, not issue
        (c7,) = verify(student_a(), docs, CFG).by_code("C7")
        self.assertEqual((c7.result, c7.severity), (Result.FAIL, Severity.WARNING))

    def test_expired_ncl(self):
        docs = student_a_docs()
        docs["NCL"].fields["valid_upto"] = F("31-Mar-2026")
        (c8,) = verify(student_a(), docs, CFG).by_code("C8")
        self.assertEqual(c8.result, Result.FAIL)
        self.assertIn("Obtain a new certificate", c8.message)

    def test_wrong_category_chosen(self):
        st = student_a()
        st.category = "NT_C"
        (c10,) = verify(st, student_a_docs(), CFG).by_code("C10")
        self.assertEqual(c10.result, Result.FAIL)

    def test_category_aliases(self):
        self.assertEqual(CFG.category_from_text("Nomadic Tribe(C)"), "NT_C")
        self.assertEqual(CFG.category_from_text("a Socially and Educationally Backward Class"), "SEBC")
        self.assertEqual(CFG.category_from_text("Scheduled Tribe"), "ST")

    def test_dob_mismatch(self):
        docs = student_a_docs()
        docs["LEAVING_CERT"].fields["dob"] = F("02/06/2008")
        (x2,) = verify(student_a(), docs, CFG).by_code("X2")
        self.assertEqual(x2.result, Result.FAIL)

    def test_name_mismatch_across_documents(self):
        docs = student_a_docs()
        docs["DOMICILE"].fields["name"] = F("Asha Kiran Patil")
        x1 = [f for f in verify(student_a(), docs, CFG).by_code("X1") if "DOMICILE" in f.documents]
        self.assertEqual(x1[0].result, Result.FAIL)

    def test_wrong_document_uploaded(self):
        docs = student_a_docs()
        docs["HSC_MARKSHEET"].classifier_match = False
        res = verify(student_a(), docs, CFG)
        self.assertEqual(res.by_code("Q2")[0].result, Result.FAIL)
        self.assertEqual(res.eligibility, {})

    def test_low_aggregate_for_open(self):
        docs = {"HSC_MARKSHEET": ExtractedDocument(
            "HSC_MARKSHEET", "HSC_MH", fields={"name": F("Rohan Jadhav"), "seat_no": F("1"), "result": F("PASS")},
            subjects=[{"name": "PHYSICS", "obtained": 42}, {"name": "MATHEMATICS", "obtained": 43},
                      {"name": "CHEMISTRY", "obtained": 44}])}
        st = Student("AV-1", "Rohan Jadhav", "OPEN")
        (e4,) = verify(st, docs, CFG).by_code("E4")
        self.assertEqual(e4.result, Result.FAIL)  # 43% < 45% for Open
        st.category = "SC"
        (e4,) = verify(st, docs, CFG).by_code("E4")
        self.assertEqual(e4.result, Result.PASS)  # 43% >= 40% reserved

    def test_cbse_student(self):
        st = Student("AV-2", "Ananya Mahesh Kulkarni", "OPEN")
        res = verify(st, {"HSC_MARKSHEET": cbse_hsc()}, CFG)
        self.assertEqual(res.eligibility["pcm_percent"], 66.33)
        self.assertEqual(res.by_code("E4")[0].result, Result.PASS)

    def test_ews_year(self):
        st = Student("AV-3", "Neha Shah", "EWS")
        docs = {"EWS_CERT": ExtractedDocument("EWS_CERT", "ANNEX_A", fields={
            "name": F("Kumari Neha Ramesh Shah"), "certificate_no": F("4200000001"),
            "issue_date": F("14/06/2026"), "valid_for_year": F("(Valid for Year 2026-2027 )")})}
        (c9,) = verify(st, docs, CFG).by_code("C9")
        self.assertEqual(c9.result, Result.PASS)

    def test_catalog_requirements_reference_known_documents(self):
        known = set(CFG.doc_types)
        for cat, docs in CFG.catalog["category_requirements"].items():
            if cat.startswith("_"):
                continue
            self.assertTrue(set(docs) <= known, cat)
        cats = {c["code"] for c in CFG.catalog["categories"]}
        self.assertEqual(cats, {k for k in CFG.catalog["category_requirements"] if not k.startswith("_")})


if __name__ == "__main__":
    unittest.main()
