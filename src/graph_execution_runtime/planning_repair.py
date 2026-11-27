"""Persistent, bounded model-facing repair feedback for autonomous planning."""
from __future__ import annotations
import json
from .planning_validation import PlanningInputError
from .pipeline import atomic_json

class PlanningRepair:
    def __init__(self,pipeline):
        self.pipeline=pipeline
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
        try:return self.pipeline.finish(stage,evidence)
        except PlanningInputError as exc:return self.reject(stage,exc)
        except (KeyError,TypeError,AttributeError):
            # Malformed team shape, not a failed system/authorization operation.
            if stage!="backlog-team-designer":raise
            return self.reject(stage,PlanningInputError("TEAM_SHAPE_INVALID","Use the exact task graph, team roster and assignment schema from the stage contract.","team-definition.json"))
