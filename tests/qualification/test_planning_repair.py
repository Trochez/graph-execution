"""Regression for live L01 missing-unit failure and bounded same-session repair."""
import json
import tempfile
import unittest
from pathlib import Path
from graph_execution_runtime.pipeline import Pipeline,PLAN,TEAM
from graph_execution_runtime.planning_repair import PlanningRepair
from graph_execution_runtime.planning_validation import schema

class PlannerFeedback(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);plan=self.root/"plan.md";plan.write_text("# Implement a file")
        self.pipe=Pipeline(plan,self.root/"run",Path(__file__).resolve().parents[2]);self.pipe.init()
        self.repair=PlanningRepair(self.pipe);self.repair.begin(PLAN)
        self.repair.write(PLAN,"backlog.md","# Backlog")
        self.rows=[{"id":"A","duration":1,"source":"plan#implement","outcome":"file","verification":"actual test","depends_on":[]}]
    def put(self,doc):
        return self.repair.write(PLAN,"tasks.json",json.dumps(doc))
    def test_exact_live_failure_then_repair(self):
        self.put({"tasks":self.rows})
        bad=self.repair.finish(PLAN,"review")
        self.assertEqual(bad["code"],"DURATION_UNIT_REQUIRED")
        self.assertEqual(bad["status"],"repair_required")
        self.assertEqual(bad["artifact"],"tasks.json")
        self.assertEqual(bad["repairs_remaining"],1)
        self.assertEqual(self.pipe.read()["active_stage"],PLAN)
        self.assertEqual(self.pipe.read()["stages"][TEAM]["status"],"pending")
        self.assertNotIn("unit",json.loads((self.pipe.run_dir/PLAN/"tasks.json").read_text()))
        # A new bridge instance retains the repair counter and can finish.
        self.repair=PlanningRepair(self.pipe)
        self.put({"unit":"hours","tasks":self.rows})
        done=self.repair.finish(PLAN,"actual estimate unit confirmed")
        self.assertEqual(done["stages"][PLAN]["status"],"completed")
        self.assertTrue((self.pipe.run_dir/PLAN/"dag-analysis.json").is_file())
        self.assertEqual(self.repair.begin(TEAM)["active_stage"],TEAM)
    def test_two_failures_block_no_restart(self):
        self.put({"tasks":self.rows})
        self.assertEqual(self.repair.finish(PLAN,"review")["status"],"repair_required")
        again=PlanningRepair(self.pipe)
        self.assertEqual(again.finish(PLAN,"review")["status"],"blocked")
        self.assertEqual(again.begin(PLAN)["status"],"blocked")
        self.assertEqual(self.pipe.read()["stages"][PLAN]["status"],"blocked")
        with self.assertRaises(ValueError):again.begin(TEAM)
    def test_invalid_json_returns_feedback(self):
        bad=self.repair.write(PLAN,"tasks.json","{")
        self.assertEqual(bad["code"],"JSON_INVALID")
        self.put({"unit":"hours","tasks":self.rows})
        self.assertEqual(self.repair.finish(PLAN,"review")["stages"][PLAN]["status"],"completed")
    def test_cycle_not_silently_repaired(self):
        self.rows[0]["depends_on"]=["A"]
        self.put({"unit":"hours","tasks":self.rows})
        r=self.repair.finish(PLAN,"review")
        self.assertEqual(r["code"],"DEPENDENCY_CYCLE")
        self.assertFalse((self.pipe.run_dir/PLAN/"dag-analysis.json").exists())
    def test_schema_unit_is_explicit(self):
        self.assertEqual(schema(PLAN)["tasks_json_example"]["unit"],"hours")
        self.assertIn("unit",schema(PLAN)["tasks_json_example"])
