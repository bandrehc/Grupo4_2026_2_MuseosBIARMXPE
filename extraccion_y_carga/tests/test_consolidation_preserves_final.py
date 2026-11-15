"""Regresión: limpiar crudos no debe borrar el corpus al consolidar otra vez."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "repos_wrapper"))
from review_corpus import REVIEW_FIELDS, load_consolidation_reviews


class PreserveFinalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name) / "raw.csv"
        self.final = Path(self.temp.name) / "final.csv"

    def write(self, path, identifiers):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            for identifier in identifiers:
                row = dict.fromkeys(REVIEW_FIELDS, "")
                row.update(google_place_id="museo-1", id_review=identifier, rating="5")
                writer.writerow(row)

    def unique_ids(self):
        frame = load_consolidation_reviews(self.raw, self.final)
        return set(frame.drop_duplicates(["google_place_id", "id_review"])["id_review"])

    def test_final_without_raw(self):
        self.write(self.final, ["001", "002"])
        self.assertEqual(self.unique_ids(), {"001", "002"})

    def test_new_incremental_preserves_old_rows(self):
        self.write(self.final, ["001", "002"])
        self.write(self.raw, ["002", "003"])
        self.assertEqual(self.unique_ids(), {"001", "002", "003"})

    def test_first_run_raw_only(self):
        self.write(self.raw, ["001"])
        self.assertEqual(self.unique_ids(), {"001"})

    def test_missing_sources_fails(self):
        with self.assertRaises(FileNotFoundError):
            load_consolidation_reviews(self.raw, self.final)

    def test_wrong_schema_fails(self):
        self.final.write_text("id_review\n001\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_consolidation_reviews(self.raw, self.final)


if __name__ == "__main__":
    unittest.main()
