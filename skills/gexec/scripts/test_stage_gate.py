import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import stage_gate


class StageGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.plan = self.write("plan.md", "plan")
        self.manifest = self.root / "state.json"
        self.state = stage_gate.init(self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, content):
        path = self.root / name
        path.write_text(content)
        return path

    def complete(self, stage, output):
        stage_gate.start(self.state, stage)
        stage_gate.finish(self.state, stage, [self.write(output, output)], "verified")

    def test_order_barrier_and_blocked_transition(self):
        with self.assertRaises(ValueError):
            stage_gate.start(self.state, "backlog-team-designer")
        stage_gate.start(self.state, "critical-path-planner")
        with self.assertRaises(ValueError):
            stage_gate.start(self.state, "native-plan-executor")
        stage_gate.fail(self.state, "critical-path-planner", "needs repair")
        self.assertEqual(self.state["stages"]["critical-path-planner"]["status"], "blocked")
        stage_gate.start(self.state, "critical-path-planner")
        stage_gate.finish(self.state, "critical-path-planner", [self.write("a", "a")], "ok")
        stage_gate.start(self.state, "backlog-team-designer")

    def test_inputs_must_match_before_finish_and_evidence_required(self):
        stage_gate.start(self.state, "critical-path-planner")
        self.plan.write_text("changed")
        with self.assertRaises(ValueError):
            stage_gate.finish(self.state, "critical-path-planner", [self.write("a", "a")], "ok")
        self.plan.write_text("plan")
        # The failed finish leaves the stage running; fail is the explicit recovery transition.
        stage_gate.fail(self.state, "critical-path-planner", "restart")
        stage_gate.start(self.state, "critical-path-planner")
        with self.assertRaises(ValueError):
            stage_gate.finish(self.state, "critical-path-planner", [self.write("a", "a")], " ")

    def test_reconcile_invalidates_earliest_and_downstream_without_deleting_files(self):
        self.complete("critical-path-planner", "a")
        self.complete("backlog-team-designer", "b")
        self.complete("native-plan-executor", "c")
        (self.root / "a").write_text("edited")
        original_output = self.state["stages"]["critical-path-planner"]["output_fingerprints"][0]
        self.assertEqual(stage_gate.reconcile(self.state), "critical-path-planner")
        self.assertEqual(self.state["history"][-1]["records"]["critical-path-planner"]["output_fingerprints"][0], original_output)
        self.assertEqual([self.state["stages"][s]["status"] for s in stage_gate.STAGES], ["pending"] * 3)
        self.assertTrue((self.root / "b").exists())
        self.assertTrue((self.root / "c").exists())

    def test_reconcile_updates_plan_baseline_and_resume_reuses_valid_receipts(self):
        self.complete("critical-path-planner", "a")
        self.assertIsNone(stage_gate.reconcile(self.state))
        self.assertEqual(self.state["stages"]["critical-path-planner"]["status"], "completed")
        self.plan.write_text("new plan")
        self.assertEqual(stage_gate.reconcile(self.state), "critical-path-planner")
        self.assertEqual(self.state["plan"]["sha256"], stage_gate.fingerprint(self.plan)["sha256"])

    def test_explicit_invalidation_archives_receipts_and_preserves_predecessor(self):
        self.complete("critical-path-planner", "a")
        self.complete("backlog-team-designer", "b")
        self.complete("native-plan-executor", "c")
        first_receipt = dict(self.state["stages"]["critical-path-planner"])
        second_receipt = dict(self.state["stages"]["backlog-team-designer"])
        self.assertEqual(stage_gate.invalidate(self.state, "backlog-team-designer", "meaning changed"), "backlog-team-designer")
        self.assertEqual(self.state["stages"]["critical-path-planner"], first_receipt)
        self.assertEqual(self.state["stages"]["backlog-team-designer"]["status"], "pending")
        archived = self.state["history"][-1]
        self.assertEqual(archived["records"]["backlog-team-designer"], second_receipt)
        self.assertEqual(archived["records"]["backlog-team-designer"]["output_fingerprints"][0]["path"], str((self.root / "b").resolve()))
        self.assertTrue((self.root / "b").exists())
        self.assertTrue((self.root / "c").exists())

    def test_explicit_invalidation_refuses_active_stage(self):
        stage_gate.start(self.state, "critical-path-planner")
        with self.assertRaises(ValueError):
            stage_gate.invalidate(self.state, "critical-path-planner", "stale")

    def test_non_object_manifest_returns_cli_error(self):
        self.manifest.write_text("[]")
        script = Path(__file__).with_name("stage_gate.py")
        result = subprocess.run([sys.executable, str(script), "reconcile", str(self.manifest)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("malformed", result.stderr.lower())

    def test_active_running_state_cannot_reconcile(self):
        stage_gate.start(self.state, "critical-path-planner")
        with self.assertRaises(ValueError):
            stage_gate.reconcile(self.state)

    def test_finish_rejects_invalid_outputs_and_plan_as_output(self):
        stage_gate.start(self.state, "critical-path-planner")
        with self.assertRaises(ValueError):
            stage_gate.finish(self.state, "critical-path-planner", [self.plan], "ok")
        with self.assertRaises(ValueError):
            stage_gate.finish(self.state, "critical-path-planner", [self.root / "missing"], "ok")

    def test_cli_happy_path_and_existing_manifest_error(self):
        script = Path(__file__).with_name("stage_gate.py")
        cmd = [sys.executable, str(script)]
        result = subprocess.run(cmd + ["init", str(self.manifest), "--plan", str(self.plan)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.manifest.read_text())["plan"]["path"], str(self.plan.resolve()))
        again = subprocess.run(cmd + ["init", str(self.manifest), "--plan", str(self.plan)], capture_output=True, text=True)
        self.assertEqual(again.returncode, 2)
        self.assertIn("exists", again.stderr.lower())
        start = subprocess.run(cmd + ["start", str(self.manifest), "--stage", stage_gate.STAGES[0]], capture_output=True, text=True)
        self.assertEqual(start.returncode, 0, start.stderr)
        active = json.loads(self.manifest.read_text())
        self.assertEqual(active["active_stage"], stage_gate.STAGES[0])


if __name__ == "__main__":
    unittest.main()
