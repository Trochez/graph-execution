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


class AutonomousScopeFeedback(unittest.TestCase):
    def setUp(self):
        PlannerFeedback.setUp(self)
        self.profile={"schema":2,"paths":["orderlib","order_cli","requirements.txt","obsolete.txt","tests"],
            "write_paths":["orderlib","order_cli","requirements.txt","obsolete.txt"],
            "required_parallel_roots":["orderlib/validation.py","order_cli"],"require_independent_review":True,
            "directory_files":{"order_cli":["order_cli/__main__.py"]}}
        self.repair=PlanningRepair(self.pipe,self.profile)
        self.rows=[{"id":k,"duration":1,"source":"PLAN.md","outcome":"actual result","verification":"check","depends_on":deps}
            for k,deps in [("T1",[]),("T2",[]),("T3",[]),("T4",["T1","T2","T3"]),("T5",["T4"])]]
    def put(self,doc):
        return PlannerFeedback.put(self,doc)
    def fix_rows(self):
        for row,scope in zip(self.rows,[["orderlib/validation.py"],["order_cli","requirements.txt"],["obsolete.txt"],[],[]]):
            row["write_scope"]=scope
    def test_exact_live_missing_scopes_repaired_before_finish(self):
        bad=self.put({"unit":"hours","tasks":self.rows})
        self.assertEqual(bad["code"],"WRITE_SCOPE_REQUIRED")
        self.assertIn("T1, T2, T3, T4, T5",bad["message"])
        self.assertEqual(bad["repairs_remaining"],1)
        self.assertFalse((self.pipe.run_dir/PLAN/"dag-analysis.json").exists())
        before=json.loads((self.pipe.run_dir/PLAN/"tasks.json").read_text())["tasks"]
        self.fix_rows()
        self.assertIsInstance(self.put({"unit":"hours","tasks":self.rows}),str)
        self.assertEqual(self.repair.finish(PLAN,"actual verified scopes")["stages"][PLAN]["status"],"completed")
        self.assertEqual([{k:v for k,v in t.items() if k!="write_scope"} for t in self.rows],before)
    def test_finish_cannot_bypass_scope_metadata_gate(self):
        self.pipe.put(PLAN,"tasks.json",json.dumps({"unit":"hours","tasks":self.rows}))
        self.assertEqual(self.repair.finish(PLAN,"review")["code"],"WRITE_SCOPE_REQUIRED")
    def test_unauthorized_write_group_rejected_early(self):
        self.fix_rows();self.rows[1]["write_scope"]=["tests/test_validation.py"]
        self.assertEqual(self.put({"unit":"hours","tasks":self.rows})["code"],"WRITE_SCOPE_NOT_APPROVED")
    def test_wrong_scope_type_rejected(self):
        self.fix_rows();self.rows[0]["write_scope"]="orderlib/validation.py"
        self.assertEqual(self.put({"unit":"hours","tasks":self.rows})["code"],"WRITE_SCOPE_INVALID")
    def test_undeclared_directory_child_rejected_early(self):
        self.fix_rows();self.rows[1]["write_scope"]=["order_cli/unknown.py"]
        self.assertEqual(self.put({"unit":"hours","tasks":self.rows})["code"],"WRITE_SCOPE_NOT_APPROVED")
