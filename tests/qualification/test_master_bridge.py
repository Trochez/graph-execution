"""Actual Pydantic Agent + bridge tools for phase-scoped planning and compilation.
FunctionModel supplies scripted responses; no provider requests or Docker required.
The separate autonomous_runtime_smoke exercises real Docker/Temporal/Git execution.
"""
import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from pydantic_ai import ModelResponse,TextPart,ToolCallPart
from pydantic_ai.models.function import FunctionModel
from graph_execution_runtime.pipeline import Pipeline,PLAN,TEAM
from graph_execution_runtime.master_phases import TOOLS,next_phase
from graph_execution_runtime.gitstage import git,inspect,Staging
from graph_execution_runtime.policy import digest

class MasterBridgeTests(unittest.TestCase):
    def test_actual_phase_tools_and_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);root=d/"project";root.mkdir()
            (root/"src").mkdir();(root/"src/a.py").write_text("a=1\n");(root/"src/b.py").write_text("b=1\n")
            git(root,"init","-b","main");git(root,"add",".");git(root,"commit","-m","seed")
            baseline=inspect(root)
            run=d/"run";run.mkdir();plan=run/"PLAN.md";plan.write_text("# Independent files and review\n")
            wheel=d/"wheels";wheel.mkdir();skill_root=Path(__file__).resolve().parents[2]
            checks=[["python","-c","assert True"]]
            profile={"schema":2,"workspace":str(root),"image":"python@sha256:"+"a"*64,"wheelhouse":str(wheel),
                "wheels":{},"paths":["src"],"commands":["python"],"checks":checks,"final_checks":checks,
                "capacity":2,"timeout":300,"acknowledge":"local-trusted-docker-offline","model":"openai:fixture",
                "base_url":"http://localhost:20128/v1","approval":str(d/"approval.json"),"skill_root":str(skill_root),
                "required_parallel_roots":["src/a.py","src/b.py"],"require_independent_review":True}
            pp=d/"profile.json";pp.write_text(json.dumps(profile));pp.chmod(0o600)
            run_id="gexec-"+uuid4().hex
            planning={"run_id":run_id,"run_dir":str(run),"plan":str(plan),"original_plan":str(plan),"workspace":str(root),
                      "profile":profile,"profile_path":str(pp),"policy_sha256":digest(profile),"baseline":baseline,
                      "skill_root":str(skill_root),"base_url":profile["base_url"],"model":profile["model"],
                      "read_paths":["src/a.py","src/b.py"]}
            cfg=run/"planning.json";cfg.write_text(json.dumps(planning))
            bp=run/"bundle.json";final=run/"final.json"
            pipe=Pipeline(plan,run,skill_root);pipe.init()
            Staging(root,profile,run_id,baseline,run/"journal/publication").start()
            rows=[{"id":k,"duration":1,"source":"PLAN.md","outcome":"result "+k,"verification":"check",
                   "depends_on":deps,"write_scope":writes} for k,deps,writes in
                  [("A",[],["src/a.py"]),("B",[],["src/b.py"]),("R",["A","B"],[])]]
            bad=json.loads(json.dumps(rows));bad[1]["depends_on"]=["A"]
            team={"agents":[{"id":k,"role":role} for k,role in [("M","master"),("A","worker"),("B","worker"),("R","reviewer")]],
                  "task_assignments":[{"task_id":k,"owner_agent_id":k,"leaf_cluster_id":"C"} for k in ("A","B","R")],
                  "clusters":[],"staffing":{},"schedule":[],"constraints":{},"alternatives":[]}
            wrong_team=json.loads(json.dumps(team));wrong_team["task_assignments"][0]["owner_agent_id"]="M"
            extension={"master":"M","roles":{a["id"]:a["role"] for a in team["agents"]},
                       "parents":{"M":None,"A":"M","B":"M","R":"M"},
                       "scopes":{t["id"]:{"reads":["src/a.py","src/b.py"] if t["id"]=="R" else [],
                                 "writes":t["write_scope"],"resources":[],"checks":checks} for t in rows}}
            compact={"scopes":{k:{"reads":v["reads"],"writes":v["writes"],"check_indices":[0]} for k,v in extension["scopes"].items()}}
            wrong_extension=json.loads(json.dumps(compact));wrong_extension["scopes"]["A"]["check_indices"]=[99]
            def write(stage,filename,content):
                return ("gexec_stage_write",{"stage":stage,"filename":filename,"content":content if isinstance(content,str) else json.dumps(content)})
            def begin(stage):return ("gexec_stage_begin",{"stage":stage})
            def finish(stage):return ("gexec_stage_finish",{"stage":stage,"evidence":"actual deterministic checks"})
            def skill(name):return ("gexec_load_skill",{"name":name})
            sequences={
                "plan":[skill("gexec"),skill(PLAN),("gexec_policy",{}),begin(PLAN),write(PLAN,"backlog.md","# Backlog"),
                        write(PLAN,"tasks.json",{"unit":"hours","tasks":bad}),finish(PLAN),
                        write(PLAN,"tasks.json",{"unit":"hours","tasks":rows}),finish(PLAN)],
                "team":[skill(TEAM),("gexec_stage_read",{"stage":PLAN,"filename":"tasks.json"}),begin(TEAM),
                        write(TEAM,"team-definition.md","# Team"),write(TEAM,"team-definition.json",wrong_team),
                        write(TEAM,"task-graph.json",{"tasks":rows,"couplings":[]}),finish(TEAM),
                        write(TEAM,"team-definition.json",team),finish(TEAM)],
                "prepare":[skill("native-plan-executor"),("gexec_skill_reference",{"name":"pax-protocol"}),
                           ("gexec_stage_read",{"stage":TEAM,"filename":"team-definition.json"}),
                           ("gexec_prepare_autonomous",{"extension":wrong_extension}),
                           ("gexec_prepare_autonomous",{"extension":compact})]}
            try:
                with patch.dict(os.environ,{"GEXEC_RUN_BUNDLE":str(bp),"GEXEC_PIPELINE_CONFIG":str(cfg),
                    "GEXEC_PROBE_API_KEY":"synthetic-not-a-secret"}):
                    for phase in ("plan","team","prepare"):
                        self.assertEqual(next_phase(pipe,bp,final),phase)
                        os.environ["GEXEC_MASTER_PHASE"]=phase
                        script=sequences[phase];index=0
                        def respond(messages,info):
                            nonlocal index
                            exposed={t.name for t in info.function_tools}
                            self.assertEqual(exposed,TOOLS[phase])
                            if phase=="plan" and index==7:
                                returns=[p.content for m in messages for p in m.parts if p.part_kind=="tool-return" and p.tool_name=="gexec_stage_finish"]
                                self.assertEqual(returns[-1]["code"],"TOPOLOGY_CONTRACT")
                            if phase=="team" and index==7:
                                returns=[p.content for m in messages for p in m.parts if p.part_kind=="tool-return" and p.tool_name=="gexec_stage_finish"]
                                self.assertEqual(returns[-1]["code"],"MASTER_TASK_OWNER")
                            if phase=="prepare" and index==4:
                                returns=[p.content for m in messages for p in m.parts if p.part_kind=="tool-return" and p.tool_name=="gexec_prepare_autonomous"]
                                self.assertEqual(returns[-1]["code"],"CHECK_INDICES")
                            if index==len(script):
                                return ModelResponse(parts=[TextPart("phase completed")])
                            name,args=script[index];index+=1
                            return ModelResponse(parts=[ToolCallPart(name,args)])
                        model=FunctionModel(respond)
                        with patch("graph_execution_runtime.operator.model_factory",return_value=model):
                            if "graph_execution_runtime.pax_bridge" in sys.modules:
                                bridge=importlib.reload(sys.modules["graph_execution_runtime.pax_bridge"])
                            else:bridge=importlib.import_module("graph_execution_runtime.pax_bridge")
                            asyncio.run(bridge.agent.run("Run this synthetic phase."))
                        self.assertEqual(index,len(script))
                    self.assertEqual(next_phase(pipe,bp,final),"execute")
                    self.assertEqual(len(list((run/"skill-loads").glob("*.json"))),4)
                    self.assertTrue(bp.is_file())
                    self.assertEqual(inspect(root),baseline)
                    spec=json.loads(bp.read_text())["spec"]
                    self.assertEqual(spec["tasks"]["A"]["dependencies"],[])
                    self.assertEqual(spec["tasks"]["B"]["dependencies"],[])
                    self.assertEqual(spec["agents"]["R"]["role"],"reviewer")
                    # Import executor with its actual existing bundle; expose only
                    # read/review/execute tools, never planning or preparation.
                    os.environ["GEXEC_MASTER_PHASE"]="execute"
                    def inspect_tools(messages,info):
                        self.assertEqual({t.name for t in info.function_tools},TOOLS["execute"])
                        return ModelResponse(parts=[TextPart("execution tools inspected")])
                    with patch("graph_execution_runtime.operator.model_factory",return_value=FunctionModel(inspect_tools)):
                        bridge=importlib.reload(sys.modules["graph_execution_runtime.pax_bridge"])
                        asyncio.run(bridge.agent.run("Inspect tools only. No dispatch."))
            finally:
                sys.modules.pop("graph_execution_runtime.pax_bridge",None)
