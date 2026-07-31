from __future__ import annotations

import importlib.util
import hashlib
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "run-portfolio-homologation-case.py"
SPEC = importlib.util.spec_from_file_location("run_portfolio_homologation_case", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PortfolioHomologationCaseTests(unittest.TestCase):
    def test_instance_isolated_identifiers_without_mutating_canonical_case(self) -> None:
        canonical, dataset, _ = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)

        instance = MODULE.instantiate_case(canonical, "vp-demo-20260723")

        self.assertEqual(canonical["case_id"], "internal-commercial-opportunity-copilot-v1")
        self.assertEqual(
            instance["case_id"],
            "internal-commercial-opportunity-copilot-v1-vp-demo-20260723",
        )
        self.assertTrue(instance["contract"]["number"].endswith("-vp-demo-20260723"))
        self.assertTrue(instance["engagement"]["name"].endswith("· vp-demo-20260723"))
        self.assertTrue(instance["knowledge_base"]["name"].endswith("· vp-demo-20260723"))
        self.assertEqual(instance["contract"]["commercial_metadata"]["instance_id"], "vp-demo-20260723")
        self.assertEqual(MODULE.validate_case(instance, dataset)["status"], "valid")

    def test_instance_id_rejects_unsafe_or_ambiguous_values(self) -> None:
        canonical, _, _ = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)

        for value in ("../vp", "vp demo", "-vp", "vp/demo"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                MODULE.instantiate_case(canonical, value)

    def test_instance_can_reuse_only_the_same_tenant_canonical_knowledge_base(self) -> None:
        canonical, _, _ = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)

        instance = MODULE.instantiate_case(
            canonical,
            "vp-demo-20260723",
            reuse_canonical_knowledge=True,
        )

        self.assertEqual(instance["knowledge_base"]["name"], canonical["knowledge_base"]["name"])
        self.assertNotEqual(instance["contract"]["number"], canonical["contract"]["number"])
        self.assertNotEqual(instance["engagement"]["name"], canonical["engagement"]["name"])

    def test_canonical_source_checksum_matches_knowledge_normalization(self) -> None:
        _, _, sources = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)
        content = sources["case.json"]

        checksum = hashlib.sha256(content.replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()

        self.assertEqual(len(checksum), 64)

    def test_held_out_labels_are_not_bootstrapped_into_agent_knowledge(self) -> None:
        case, dataset, sources = MODULE.load_case(MODULE.DEFAULT_CASE_DIR)

        validation = MODULE.validate_case(case, dataset)

        self.assertEqual(validation["evaluation_scenarios"], 24)
        self.assertEqual(validation["adversarial_scenarios"], 8)
        self.assertTrue(validation["held_out_labels"])
        self.assertNotIn("evaluation-dataset.jsonl", sources)
        self.assertIn("evaluation-inputs.jsonl", sources)
        self.assertNotIn("expected_primary_offering", sources["evaluation-inputs.jsonl"])


if __name__ == "__main__":
    unittest.main()
