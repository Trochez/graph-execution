"""Adapter around the unchanged legacy sequential stage gate."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import load_json
from .planning_validation import PlanningInputError,check_tasks,helper_error

PLAN="critical-path-planner"
TEAM="backlog-team-designer"
EXEC="native-plan-executor"
OUTPUTS={PLAN:("backlog.md","tasks.json"), TEAM:("team-definition.md","team-definition.json","task-graph.json")}
DERIVED={PLAN:("tasks.json","dag-analysis.json","analyze_dag.py"),TEAM:("task-graph.json","graph-analysis.json","analyze_team_graph.py")}


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".gexec-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(value,f,indent=2,sort_keys=True);f.write("\n")
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


class Pipeline:
    def __init__(self, plan: Path, run_dir: Path, skill_root: Path):
        self.plan=plan.resolve(strict=True)
        self.run_dir=run_dir.resolve()
        self.skill_root=skill_root.resolve(strict=True)
        self.manifest=self.run_dir/"pipeline.json"
        for name in (PLAN,TEAM,EXEC,"gexec"):
            if not (self.skill_root/"skills"/name/"SKILL.md").is_file():
                raise ValueError("missing required skill: "+name)
        file=self.skill_root/"skills/gexec/scripts/stage_gate.py"
        spec=importlib.util.spec_from_file_location("legacy_stage_gate",file)
        self.gate=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)

    def read(self):
        s=self.gate._read(self.manifest)
        if s["plan"]["path"] != str(self.plan):
            raise ValueError("pipeline plan mismatch")
        return s

    def init(self):
        self.run_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        if not self.manifest.exists():
            self.gate._write(self.manifest,self.gate.init(self.plan),refuse_existing=True)
        return self.read()

    def begin(self,stage):
        if stage not in (PLAN,TEAM):
            raise ValueError("only approved runtime can start executor")
        s=self.read()
        if sum(e.get("stage")==stage and e.get("event")=="blocked" for e in s["history"])>=2:
            raise ValueError("focused stage repair exhausted")
        self.gate.start(s,stage)
        self.gate._write(self.manifest,s)
        return s

    def put(self,stage,name,content):
        if stage not in OUTPUTS or name not in OUTPUTS[stage] or self.read()["active_stage"]!=stage:
            raise PermissionError("artifact outside active stage")
        if not isinstance(content,str) or len(content.encode("utf-8"))>524288:
            raise ValueError("artifact too large")
        dest=self.run_dir/stage/name
        dest.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        if dest.is_symlink():
            raise ValueError("unsafe artifact")
        if name.endswith(".json"):
            atomic_json(dest,json.loads(content))
        else:
            fd,tmp=tempfile.mkstemp(dir=dest.parent,prefix=".gexec-")
            try:
                with os.fdopen(fd,"w",encoding="utf-8") as f:f.write(content)
                os.replace(tmp,dest)
            finally:
                if os.path.exists(tmp):os.unlink(tmp)
        return str(dest)

    def get(self,stage,name):
        permitted=OUTPUTS.get(stage,())+((DERIVED[stage][1],) if stage in DERIVED else ())
        if name not in permitted:
            raise PermissionError("unknown stage artifact")
        p=self.run_dir/stage/name
        if p.is_symlink() or p.stat().st_size>524288:
            raise ValueError("unsafe or oversize artifact")
        return p.read_text(encoding="utf-8")

    def finish(self,stage,evidence):
        if stage not in OUTPUTS:
            raise PermissionError("executor completion is runtime-controlled")
        s=self.read()
        if s["active_stage"]!=stage:
            raise ValueError("not active stage")
        directory=self.run_dir/stage
        files=[directory/name for name in OUTPUTS[stage]]
        missing=[p.name for p in files if not p.is_file() or p.is_symlink() or p.stat().st_size==0]
        if missing:
            raise PlanningInputError("ARTIFACT_MISSING","Write the missing or empty required artifact(s): "+", ".join(missing),missing[0])
        if stage==PLAN:
            try:doc=load_json(directory/"tasks.json")
            except json.JSONDecodeError as exc:raise PlanningInputError("JSON_INVALID",f"tasks.json invalid JSON at line {exc.lineno}, column {exc.colno}.","tasks.json") from None
            check_tasks(doc)
        input_name,output_name,helper=DERIVED[stage]
        calc=subprocess.run([sys.executable,str(self.skill_root/"skills"/stage/"scripts"/helper),
                             str(directory/input_name)],capture_output=True,timeout=20,text=True)
        if calc.returncode!=0:
            raise helper_error(input_name,calc.stderr)
        atomic_json(directory/output_name,json.loads(calc.stdout))
        if stage==PLAN:
            tasks=load_json(directory/"tasks.json")["tasks"]
            for task in tasks:
                if any(not task.get(k) for k in ("id","source","outcome","verification")):
                    raise ValueError("missing source, outcome or acceptance criteria")
        else:
            prior=load_json(self.run_dir/PLAN/"tasks.json")["tasks"]
            graph=load_json(directory/"task-graph.json")["tasks"]
            team=load_json(directory/"team-definition.json")
            def deps(rows):
                return {t["id"]:sorted(t.get("depends_on",[])) for t in rows}
            if len(graph)!=len(prior) or deps(graph)!=deps(prior):
                raise PlanningInputError("DAG_CHANGED","The team graph must preserve all validated task IDs and dependency edges.","task-graph.json")
            ids=set(deps(prior));assign=team["task_assignments"];agents={a["id"] for a in team["agents"]}
            if len(assign)!=len(ids) or {a["task_id"] for a in assign}!=ids or any(a["owner_agent_id"] not in agents for a in assign):
                raise PlanningInputError("ASSIGNMENT_COVERAGE","Assign every task exactly once to an agent in the roster.","team-definition.json")
            for key in ("clusters","staffing","schedule","constraints","alternatives"):
                if key not in team:raise PlanningInputError("TEAM_FIELD_REQUIRED","Required team field: "+key,"team-definition.json")
        self.gate.finish(s,stage,[*files,directory/output_name],evidence)
        self.gate._write(self.manifest,s)
        return s

    def fail(self,stage,reason):
        if stage not in (PLAN,TEAM):raise PermissionError("not a planning stage")
        s=self.read();self.gate.fail(s,stage,reason);self.gate._write(self.manifest,s);return s

    def bind(self,tasks:Path,team:Path):
        s=self.read()
        # Existing helper verifies source and both stage fingerprints.
        self.gate._inputs(s,2)
        if tasks.resolve()!=self.run_dir/PLAN/"tasks.json" or team.resolve()!=self.run_dir/TEAM/"team-definition.json":
            raise ValueError("must use exact verified pipeline artifacts")
        return s

    def start_executor(self,tasks,team):
        s=self.bind(tasks,team)
        if s["active_stage"]==EXEC:
            return s
        self.gate.start(s,EXEC);self.gate._write(self.manifest,s);return s

    def finish_executor(self,outputs,evidence):
        s=self.read()
        if s["stages"][EXEC]["status"]=="completed":
            return s
        self.gate.finish(s,EXEC,outputs,evidence);self.gate._write(self.manifest,s);return s
