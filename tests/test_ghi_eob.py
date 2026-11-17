import json
import unittest
from pathlib import Path

from ghi_eob.parser import NotAnEOB, parse
from ghi_eob.plan import filings_for, guess_provider_names, tracker_updates

FIXTURES = Path(__file__).parent / "fixtures"
SETTINGS = json.loads((FIXTURES / "settings.json").read_text())

HEADER = ["D.O.S.", "Year", "Type", "Patient", "Provider", "GHI", "Claim #", "GHI Paid", "Paid To"]


def fixture(name):
    return parse((FIXTURES / name).read_text())


class ParserTests(unittest.TestCase):
    def test_single_visit(self):
        eob = fixture("single_visit_paid_to_provider.txt")
        self.assertFalse(eob.has_check)
        (claim,) = eob.claims
        self.assertEqual(claim.patient, "JANE DOE")
        self.assertEqual(claim.claim_number, "11111111111")
        self.assertEqual(claim.provider, "SAMPLE,ANNA,NP PNP RN")
        self.assertEqual([(l.date, l.plan_paid, l.you_may_owe) for l in claim.lines],
                         [("2026-10-16", 100.13, 30.00)])
        self.assertEqual(eob.payments[0].to, "SAMPLE MEDICAL P.C.")

    def test_multi_visit_split_across_lines(self):
        eob = fixture("multi_visit_with_check.txt")
        self.assertTrue(eob.has_check)
        (claim,) = eob.claims
        self.assertEqual(claim.patient, "SAM DOE")
        self.assertEqual(claim.provider, "EXAMPLE, VICTOR,A,PHD")
        self.assertEqual([l.date for l in claim.lines], ["2026-08-25", "2026-09-01", "2026-09-08"])
        self.assertEqual(claim.plan_paid, 377.43)
        self.assertEqual(eob.payments[0].to, "JOHN DOE")
        self.assertEqual(eob.payments[0].amount, 377.43)

    def test_rejects_other_documents(self):
        with self.assertRaises(NotAnEOB):
            parse("Explanation of Benefits\nCMM reimbursement")


class FilingTests(unittest.TestCase):
    def test_known_provider_single_date(self):
        filings, issues = filings_for(fixture("single_visit_paid_to_provider.txt"), SETTINGS)
        self.assertEqual(issues, [])
        self.assertEqual(filings[0]["file_name"], "2026-10-16 - Jane Doe - Anna Sample - GHI EOB.pdf")
        self.assertEqual(filings[0]["claim_folder"], "2026-10-16 - Jane Doe - Anna Sample")
        self.assertEqual(filings[0]["year_folder"], "2026 Claims")
        self.assertEqual(filings[0]["person_folder_id"], "folder-jane")

    def test_unknown_provider_is_guessed_and_flagged(self):
        filings, issues = filings_for(fixture("multi_visit_with_check.txt"), SETTINGS)
        self.assertEqual(filings[0]["file_name"],
                         "2026-08-25 - 2026-09-08 - Sam Doe - Dr. Example - GHI EOB & Check.pdf")
        self.assertEqual(len(issues), 1)
        self.assertIn("New provider", issues[0])

    def test_unknown_patient_not_filed(self):
        settings = dict(SETTINGS, people={})
        filings, issues = filings_for(fixture("single_visit_paid_to_provider.txt"), settings)
        self.assertEqual(filings, [])
        self.assertIn("not in settings.people", issues[0])

    def test_double_surname_matches_settings_on_last_word(self):
        from ghi_eob.plan import provider_names
        names, known = provider_names("PELCOVITZ SAMPLE,ANNA,LCSW", SETTINGS)
        self.assertTrue(known)
        self.assertEqual(names["tracker"], "Sample")

    def test_guess_names(self):
        self.assertEqual(guess_provider_names("SAMPLE,ANNA,NP PNP RN"), {"tracker": "Sample", "file": "Anna Sample"})
        self.assertEqual(guess_provider_names("ROE, RICHARD, M.D."), {"tracker": "Roe", "file": "Dr. Roe"})
        self.assertEqual(guess_provider_names("LABCORP"), {"tracker": "Labcorp", "file": "Labcorp"})


class TrackerTests(unittest.TestCase):
    def test_fills_empty_cells_on_matching_row(self):
        rows = [HEADER,
                ["2026-10-16", "2026", "Rx", "Jane", "Sample", "", "", "", ""],
                ["2026-10-16", "2026", "Medical", "Jane", "Sample", "Submitted", "", "", ""]]
        updates, issues = tracker_updates([fixture("single_visit_paid_to_provider.txt")], rows, SETTINGS)
        self.assertEqual(issues, [])
        self.assertEqual({(u["range"], u["value"]) for u in updates}, {
            ("'All Claims'!F3", "Completed"),
            ("'All Claims'!G3", "11111111111"),
            ("'All Claims'!H3", "$100.13"),
            ("'All Claims'!I3", "Provider"),
        })

    def test_already_up_to_date_makes_no_changes(self):
        rows = [HEADER, ["2026-10-16", "2026", "Medical", "Jane", "Sample", "Completed", "11111111111", "$100.13", "Provider"]]
        updates, issues = tracker_updates([fixture("single_visit_paid_to_provider.txt")], rows, SETTINGS)
        self.assertEqual((updates, issues), ([], []))

    def test_conflicting_value_is_reported_not_overwritten(self):
        rows = [HEADER, ["2026-10-16", "2026", "Medical", "Jane", "Sample", "Completed", "99999999999", "", ""]]
        updates, issues = tracker_updates([fixture("single_visit_paid_to_provider.txt")], rows, SETTINGS)
        self.assertNotIn("'All Claims'!G2", [u["range"] for u in updates])
        self.assertTrue(any("already says '99999999999'" in i for i in issues))

    def test_one_row_per_service_date_and_member_payment_leaves_paid_to_blank(self):
        settings = dict(SETTINGS, providers={"EXAMPLE": {"tracker": "Example", "file": "Dr. Example"}})
        rows = [HEADER] + [[d, "2026", "Psych", "Sam", "Example", "", "", "", ""]
                           for d in ("2026-08-25", "2026-09-01", "2026-09-08")]
        updates, issues = tracker_updates([fixture("multi_visit_with_check.txt")], rows, settings)
        self.assertEqual(issues, [])
        paid = sorted((u["range"], u["value"]) for u in updates if u["range"].split("!")[1][0] == "H")
        self.assertEqual(paid, [("'All Claims'!H2", "$125.81"), ("'All Claims'!H3", "$125.81"), ("'All Claims'!H4", "$125.81")])
        self.assertFalse(any(u["range"].split("!")[1][0] == "I" for u in updates))

    def test_missing_row_is_reported(self):
        updates, issues = tracker_updates([fixture("single_visit_paid_to_provider.txt")], [HEADER], SETTINGS)
        self.assertEqual(updates, [])
        self.assertIn("No tracker row", issues[0])


if __name__ == "__main__":
    unittest.main()
