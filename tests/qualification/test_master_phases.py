"""Reproduce stage routing failures without live model calls."""
import asyncio,json,tempfile,unittest
from pathlib import Path
from graph_execution_runtime.pipeline import Pipeline,PLAN,TEAM
from graph_execution_runtime.master_phases import next_phase,run_phases,TOOLS
from graph_execution_runtime.planning_repair import PlanningRepair
from graph_execution_runtime.parallel_contract import check_plan,check_team,check_spec,ParallelContractError
from graph_execution_runtime.budget import Budget

def row(k,dep,write):
    return {"id":k,"duration":1,"source":"plan","outcome":"actual result","verification":"check","depends_on":dep,"write_scope":write}

class MasterPhaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        d=Path(self.tmp.name);plan=d/"plan.md";plan.write_text("# Independent work")
        self.p=Pipeline(plan,d/"run",Path(__file__).resolve().parents[2]);self.p.init()
        self.b=self.p.run_dir/"bundle.json";self.final=self.p.run_dir/"final.json"
        self.rows=[row("A",[],["src/a.py"]),row("B",[],["src/b.py"]),row("R",["A","B"],[])]
        self.profile={"required_parallel_roots":["src/a.py","src/b.py"],"require_independent_review":True,"capacity":2}
        self.team={"agents":[{"id":"M","role":"master"},{"id":"A","role":"worker"},{"id":"B","role":"worker"},{"id":"R","role":"reviewer"}],"task_assignments":[{"task_id":k,"owner_agent_id":k} for k in ("A","B","R")],"clusters":[],"staffing":{},"schedule":[],"constraints":{},"alternatives":[]}
    def planner(self,rows=None):
        self.p.begin(PLAN);self.p.put(PLAN,"backlog.md","# Backlog")
        self.p.put(PLAN,"tasks.json",json.dumps({"unit":"hours","tasks":rows or self.rows}))
    def team_gate(self):
        self.p.begin(TEAM);self.p.put(TEAM,"team-definition.md","# Team")
        self.p.put(TEAM,"team-definition.json",json.dumps(self.team))
        self.p.put(TEAM,"task-graph.json",json.dumps({"tasks":self.rows,"couplings":[]}))
        self.p.finish(TEAM,"verified")
    def test_context_exit_after_plan_routes_team_not_missing_bundle(self):
        self.planner();self.p.finish(PLAN,"verified")
        self.assertEqual(next_phase(self.p,self.b,self.final),"team")
        self.assertNotIn("gexec_start",TOOLS["team"])
        self.assertNotIn("gexec_prepare_autonomous",TOOLS["plan"])
        self.assertNotIn("gexec_stage_write",TOOLS["execute"])
    def test_four_phases_one_recovery_same_phase(self):
        seen=[];records=[]
        async def launch(phase,attempt,cap,prompt):
            seen.append((phase,attempt))
            if phase=="plan":
                self.planner();self.p.finish(PLAN,"verified")
            elif phase=="team":
                if attempt==1:return 2
                self.team_gate()
            elif phase=="prepare":self.b.write_text("{}")
            else:
                self.p.start_executor(self.p.run_dir/PLAN/"tasks.json",self.p.run_dir/TEAM/"team-definition.json")
                self.final.write_text('{"passed":true}')
                self.p.finish_executor([self.final],"verified")
            return 0
        n=asyncio.run(run_phases(self.p,self.b,self.final,launch,lambda:60,lambda *x:records.append(x)))
        self.assertEqual(n,1)
        self.assertEqual(seen,[("plan",1),("team",1),("team",2),("prepare",1),("execute",1)])
    def test_serial_plan_rejected_then_repaired(self):
        bad=[row("A",[],["src/a.py"]),row("B",["A"],["src/b.py"]),row("R",["B"],[])]
        self.planner(bad);r=PlanningRepair(self.p,self.profile)
        self.assertEqual(r.finish(PLAN,"review")["code"],"TOPOLOGY_CONTRACT")
        self.p.put(PLAN,"tasks.json",json.dumps({"unit":"hours","tasks":self.rows}))
        self.assertEqual(r.finish(PLAN,"verified")["stages"][PLAN]["status"],"completed")
    def test_compiler_requires_actual_schedulable_overlap(self):
        check_plan(self.profile,self.rows);check_team(self.profile,self.rows,self.team)
        spec={"agents":{a["id"]:a for a in self.team["agents"]},"tasks":{t["id"]:{"id":t["id"],"owner":t["id"],"dependencies":t["depends_on"],"writes":t["write_scope"],"reads":[],"resources":[]} for t in self.rows}}
        check_spec(self.profile,spec)
        spec["tasks"]["B"]["reads"]=["src/a.py"]
        with self.assertRaises(ParallelContractError):check_spec(self.profile,spec)
    def test_context_rejection_is_persisted_without_body(self):
        b=Budget(self.p.run_dir/"budget.db","master",60)
        with self.assertRaises(RuntimeError):b.reserve(b"x"*60001)
        self.assertEqual(b.summary()["context_rejections"],[{"actor":"master","code":"CONTEXT_BODY_LIMIT","body_bytes":60001}])
