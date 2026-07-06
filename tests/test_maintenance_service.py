import sys
import unittest
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "backend"))

from backend.services.maintenance_service import (  # noqa: E402
    detect_maintenance_type,
    parse_maintenance_entry,
)


class MaintenanceServiceTest(unittest.TestCase):
    def test_detect_maintenance_type_keeps_legacy_tuple_contract(self):
        key, label, interval_days, interval_km, score = detect_maintenance_type(
            "fiz balanceamento e rodizio dos pneus"
        )

        self.assertEqual(key, "pneus")
        self.assertEqual(label, "Pneus")
        self.assertEqual(interval_days, 180)
        self.assertEqual(interval_km, 10000)
        self.assertGreater(score, 0)

    def test_parse_entry_adds_nlp_metadata(self):
        parsed = parse_maintenance_entry(
            "troquei o oleo hoje com 50000 km e paguei R$ 350"
        )

        self.assertEqual(parsed["maintenance_type"], "troca_oleo")
        self.assertEqual(parsed["service_km"], 50000)
        self.assertEqual(parsed["next_due_km"], 60000)
        self.assertEqual(parsed["cost"], 350.0)

        metadata = parsed["parser_metadata"]
        self.assertIn(metadata["detector"], {"spacy", "keywords", "fallback"})
        self.assertIn("nlp_engine", metadata)
        self.assertIsInstance(metadata["matched_terms"], list)

    def test_parser_uses_general_maintenance_when_no_rule_matches(self):
        parsed = parse_maintenance_entry("lavagem completa ontem")

        self.assertEqual(parsed["maintenance_type"], "manutencao_geral")
        self.assertEqual(parsed["parser_metadata"]["detector"], "fallback")
        self.assertFalse(parsed["parser_metadata"]["matched_terms"])


if __name__ == "__main__":
    unittest.main()
