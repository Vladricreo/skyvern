"""Standalone learning tests without the browser/database application runtime."""

import copy
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "learning", Path(__file__).resolve().parents[2] / "skyvern/services/workflow_learning.py"
)
learning = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learning)


class LearningTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = learning.LearningStore(self.directory.name)
        self.definition = {
            "blocks": [
                {
                    "block_type": "task",
                    "label": "invoice",
                    "navigation_goal": "Download {{ count }} invoices. NEVER send or delete invoices.",
                }
            ],
            "parameters": [],
        }
        self.revision = learning.fingerprint(self.definition)

    def record(self, index, revision=None, duration=10, status="completed", eligible=True, config="same"):
        evidence = {
            "run": str(index),
            "revision": revision or self.revision,
            "status": status,
            "duration": duration,
            "credits": 1,
            "eligible": eligible,
            "execution_config": config,
            "blocks": [{"label": "invoice", "status": status}],
        }
        self.store.record("org", "workflow", evidence)
        return evidence

    def test_duplicate_is_idempotent_and_preserves_verified_outcome(self):
        row = self.record(0)
        self.store.verify("org", "workflow", "0", False, "invoice_case", "v1")
        self.store.record("org", "workflow", row)
        rows = self.store.rows("org", "workflow")
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["verified"])
        self.assertEqual(learning.summarize(rows)["verified_success_rate"], 0)

    def test_completed_is_not_verified(self):
        self.record(0)
        self.assertIsNone(learning.summarize(self.store.rows("org", "workflow"))["verified_success_rate"])

    def test_tenant_and_workflow_isolation(self):
        self.record(0)
        self.assertEqual(self.store.rows("other", "workflow"), [])
        self.assertEqual(self.store.proposals("other", "workflow"), [])
        with self.assertRaises(KeyError):
            self.store.verify("other", "workflow", "0", True, "case", "v1")
        self.assertEqual(self.store.rows("org", "other"), [])

    def test_candidate_preserves_original_constraints_placeholders_and_definition(self):
        for i in range(3):
            self.record(i, status="failed" if i == 0 else "completed")
        original = copy.deepcopy(self.definition)
        proposal = self.store.propose("org", "workflow", self.definition)
        changed = learning.candidate(self.definition, proposal)
        self.assertEqual(self.definition, original)
        self.assertTrue(changed["blocks"][0]["navigation_goal"].startswith(original["blocks"][0]["navigation_goal"]))
        self.assertEqual(changed["parameters"], original["parameters"])
        self.assertIn("retry", proposal["patches"][0]["advice"])
        self.assertEqual(proposal["candidate"], learning.fingerprint(changed))
        self.assertNotIn(
            "NEVER send", (Path(self.directory.name) / "learning.sqlite3").read_bytes().decode(errors="ignore")
        )

    def test_proposals_are_immutable_and_stale_export_rejected(self):
        for i in range(3):
            self.record(i)
        proposal = self.store.propose("org", "workflow", self.definition)
        self.record(4, status="failed")
        self.assertEqual(proposal, self.store.propose("org", "workflow", self.definition))
        changed = copy.deepcopy(self.definition)
        changed["blocks"][0]["navigation_goal"] = "Changed by user"
        with self.assertRaises(ValueError):
            learning.candidate(changed, proposal)

    def test_partial_historical_and_nonterminal_runs_do_not_generate_proposals(self):
        for i in range(4):
            self.record(i, eligible=False)
        self.record(10, status="running")
        self.assertIsNone(self.store.propose("org", "workflow", self.definition))
        self.assertEqual(len(self.store.rows("org", "workflow")), 4)

    def test_comparison_requires_matched_verified_cases_and_config(self):
        for i in range(3):
            self.record(i)
            self.record(i + 3, revision="candidate", duration=5)
        self.assertEqual(
            self.store.compare("org", "workflow", self.revision, "candidate", "v1")["recommendation"],
            "insufficient_comparable_evidence",
        )
        for i in range(6):
            self.store.verify("org", "workflow", str(i), True, "case", "v1")
        result = self.store.compare("org", "workflow", self.revision, "candidate", "v1")
        self.assertEqual(result["recommendation"], "review_candidate_for_promotion")
        self.assertFalse(result["automatic_promotion"])
        self.record(3, revision="candidate", duration=5, config="different")
        self.assertEqual(
            self.store.compare("org", "workflow", self.revision, "candidate", "v1")["recommendation"],
            "insufficient_comparable_evidence",
        )

    def test_faster_but_failed_result_is_rejected(self):
        for i in range(6):
            self.record(i, revision=self.revision if i < 3 else "candidate", duration=10 if i < 3 else 2)
            self.store.verify("org", "workflow", str(i), i != 5, "case", "v1")
        self.assertEqual(
            self.store.compare("org", "workflow", self.revision, "candidate", "v1")["recommendation"],
            "reject_quality_regression",
        )

    def test_payload_objects_are_not_treated_as_workflow_blocks(self):
        self.definition["blocks"][0]["navigation_payload"] = {
            "label": "invoice", "block_type": "task", "navigation_goal": "untrusted payload"
        }
        self.assertEqual(learning.prompt_blocks(self.definition)["invoice"], self.definition["blocks"][0])

    def test_changed_run_evidence_invalidates_previous_verification(self):
        self.record(0)
        self.store.verify("org", "workflow", "0", True, "case", "v1")
        self.record(0, duration=30)
        self.assertNotIn("verified", self.store.rows("org", "workflow")[0])

    def test_snapshot_persists_exact_execution_hash_and_partial_flag(self):
        self.store.snapshot("org", "workflow", "run", {"revision": self.revision, "eligible": False})
        reopened = learning.LearningStore(self.directory.name)
        self.assertEqual(reopened.snapshot("org", "workflow", "run"), {"revision": self.revision, "eligible": False})
        self.assertIsNone(reopened.snapshot("other", "workflow", "run"))


if __name__ == "__main__":
    unittest.main()
