"""Persistent, bounded model-facing repair feedback for autonomous planning."""
from __future__ import annotations
import json
from .planning_validation import PlanningInputError
from .pipeline import atomic_json

class PlanningRepair:
    def __init__(self,pipeline,profile=None):
        self.pipeline=pipeline;self.profile=profile or {}
        self.path=pipeline.run_dir/"planning-validation.json"
    def state(self):
        return json.loads(self.path.read_text()) if self.path.exists() else {}
    def blocked(self,stage):
        return self.state().get(stage,{}).get("terminal",False)
    def begin(self,stage):
        if self.blocked(stage):return {"accepted":False,"status":"blocked","stage":stage,"reason":"focused planning repair exhausted"}
        s=self.pipeline.read()
        if s["active_stage"]==stage:return s
        return self.pipeline.begin(stage)
    def write(self,stage,filename,content):
        if self.blocked(stage):return {"accepted":False,"status":"blocked","stage":stage}
        try:return self.pipeline.put(stage,filename,content)
        except json.JSONDecodeError as exc:
            return self.reject(stage,PlanningInputError("JSON_INVALID",f"Invalid JSON at line {exc.lineno}, column {exc.colno}. Rewrite the same artifact as valid JSON.",filename))
    def reject(self,stage,exc):
        data=self.state()
        old=data.get(stage,{"failures":0})
        if old.get("terminal"):return old["last"]
        count=old["failures"]+1
        terminal=count>=2
        result={"accepted":False,"status":"blocked" if terminal else "repair_required",
                "stage":stage,"artifact":exc.artifact,"code":exc.code,"message":str(exc),
                "validation_failures":count,"repairs_remaining":0 if terminal else 1,
                "next":"stop; do not advance or restart this stage" if terminal else "correct the named artifact, preserve requirements and call gexec_stage_finish again"}
        data[stage]={"failures":count,"terminal":terminal,"last":result}
        atomic_json(self.path,data)
        if terminal and self.pipeline.read()["active_stage"]==stage:
            self.pipeline.fail(stage,exc.code+": "+str(exc))
        return result
    def finish(self,stage,evidence):
        if self.blocked(stage):return self.state()[stage]["last"]
        try:
            from .parallel_contract import check_plan,check_team,ParallelContractError
            from .planning_validation import check_tasks
            from .pipeline import PLAN,TEAM
            if self.profile.get("schema")==2 and stage==TEAM:
                path=self.pipeline.run_dir/TEAM/"team-definition.json"
                if path.is_file():
                    from .runtime_contract import team_contract
                    rows=json.loads((self.pipeline.run_dir/PLAN/"tasks.json").read_text())["tasks"]
                    team_contract(rows,json.loads(path.read_text()))
            if self.profile.get("required_parallel_roots") or self.profile.get("require_independent_review"):
                path=self.pipeline.run_dir/PLAN/"tasks.json"
                if path.is_file():
                    rows=json.loads(path.read_text());check_tasks(rows)
                    if stage==PLAN:check_plan(self.profile,rows["tasks"])
                    elif stage==TEAM and (self.pipeline.run_dir/TEAM/"team-definition.json").is_file():
                        check_team(self.profile,rows["tasks"],json.loads((self.pipeline.run_dir/TEAM/"team-definition.json").read_text()))
            return self.pipeline.finish(stage,evidence)
        except ParallelContractError as exc:return self.reject(stage,PlanningInputError("TOPOLOGY_CONTRACT",str(exc),"tasks.json" if stage==PLAN else "team-definition.json"))
        except PlanningInputError as exc:return self.reject(stage,exc)
        except ValueError as exc:
            from .runtime_contract import RuntimeContractError
            if not isinstance(exc,RuntimeContractError):raise
            return self.reject(stage,PlanningInputError(exc.code,str(exc),"team-definition.json"))
        except (KeyError,TypeError,AttributeError):
            # Malformed team shape, not a failed system/authorization operation.
            if stage!="backlog-team-designer":raise
            return self.reject(stage,PlanningInputError("TEAM_SHAPE_INVALID","Use the exact task graph, team roster and assignment schema from the stage contract.","team-definition.json"))
