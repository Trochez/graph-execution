"""Actionable, bounded planning feedback. Never repair or infer a graph silently."""
from __future__ import annotations
import json
import math
import re
from pathlib import Path

class PlanningInputError(ValueError):
    def __init__(self,code,message,artifact):
        super().__init__(message)
        self.code=code;self.artifact=artifact

def invalid(code,message,artifact):
    raise PlanningInputError(code,message,artifact)

def check_tasks(doc):
    artifact="tasks.json"
    if not isinstance(doc,dict):
        invalid("TASKS_OBJECT_REQUIRED","tasks.json must be a JSON object with top-level unit and tasks fields.",artifact)
    if not isinstance(doc.get("unit"),str) or not doc["unit"].strip():
        invalid("DURATION_UNIT_REQUIRED","A nonempty duration unit is required at the top level of tasks.json. Specify the actual unit used for every numeric duration, e.g. hours; do not guess or mix units.",artifact)
    rows=doc.get("tasks")
    if not isinstance(rows,list) or not rows:
        invalid("TASKS_REQUIRED","tasks must be a nonempty array of task objects.",artifact)
    ids=set()
    for i,t in enumerate(rows):
        label=f"tasks[{i}]"
        if not isinstance(t,dict):invalid("TASK_OBJECT_REQUIRED",label+" must be an object.",artifact)
        k=t.get("id")
        if not isinstance(k,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",k) or k in ids:
            invalid("TASK_ID_INVALID",label+".id must be a unique task ID (letters, digits, dot, underscore or hyphen).",artifact)
        ids.add(k)
        for field in ("source","outcome","verification"):
            if not t.get(field):invalid("TASK_FIELD_REQUIRED",label+"."+field+" is required.",artifact)
        duration=t.get("duration")
        if isinstance(duration,bool) or not isinstance(duration,(int,float)):
            invalid("DURATION_REQUIRED",label+".duration must be a finite nonnegative number in the top-level unit.",artifact)
        try:valid=math.isfinite(duration) and duration>=0
        except OverflowError:valid=False
        if not valid:invalid("DURATION_REQUIRED",label+".duration must be a finite nonnegative number in the top-level unit.",artifact)
        deps=t.get("depends_on",[])
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):
            invalid("DEPENDENCIES_INVALID",label+".depends_on must contain unique task IDs.",artifact)
    for i,t in enumerate(rows):
        if not set(t.get("depends_on",[]))<=ids:
            invalid("UNKNOWN_DEPENDENCY",f"tasks[{i}].depends_on refers to an unknown ID; preserve the intended dependency and use an existing ID.",artifact)

def helper_error(artifact,stderr):
    # Fixed diagnostic vocabulary; never copy arbitrary subprocess output into
    # model history or public receipts. The unchanged helper remains authoritative.
    known=[
        ("nonempty duration unit","DURATION_UNIT_REQUIRED","Specify a nonempty top-level unit in tasks.json."),
        ("dependency cycle","DEPENDENCY_CYCLE","The dependency graph contains a cycle. Resolve it using source requirements; do not silently drop edges."),
        ("unknown dependency","UNKNOWN_DEPENDENCY","A dependency refers to an unknown task ID."),
        ("duplicate task","DUPLICATE_TASK","Task IDs must be unique."),
        ("duration must be finite","DURATION_INVALID","All task durations must be finite and nonnegative."),
        ("coupling","COUPLING_INVALID","Check the coupling endpoints, strength, kind and evidence against the team contract."),
        ("cumulative duration overflow","DURATION_OVERFLOW","The cumulative duration is not finite.")]
    for needle,code,msg in known:
        if needle in stderr.lower():return PlanningInputError(code,msg,artifact)
    return PlanningInputError("GRAPH_HELPER_REJECTED","The deterministic graph helper rejected the artifact. Check the exact stage contract and correct the graph.",artifact)

def schema(stage):
    if stage=="critical-path-planner":
        return {"reference":"skills/critical-path-planner/references/planning-contract.md",
                "required_artifacts":["backlog.md","tasks.json"],
                "tasks_json_example":{"unit":"hours","assumptions":["State actual estimation assumptions"],"tasks":[
                    {"id":"T01","title":"Example only","source":"PLAN.md#requirement","outcome":"Verifiable outcome","duration":1,"effort":1,
                     "depends_on":[],"verification":"Actual acceptance condition","write_scope":["exact authorized relative path"]}]},
                "rules":["Use a nonempty top-level unit matching all durations.","Use unique IDs and finite numeric duration per task.",
                         "Use depends_on for prerequisite IDs and preserve every source requirement.",
                         "The example is a schema illustration, never a task to copy."]}
    if stage=="backlog-team-designer":
        return {"reference":"skills/backlog-team-designer/references/team-contract.md",
                "required_artifacts":["team-definition.md","team-definition.json","task-graph.json"],
                "task_graph_json_example":{"tasks":[{"id":"T01","depends_on":[]}],"couplings":[]},
                "team_definition_json_example":{"source":"source backlog","constraints":{},"assumptions":[],"graph_analysis":{},
                    "clusters":[],"agents":[{"id":"M","role":"master"},{"id":"W","role":"worker"}],
                    "task_assignments":[{"task_id":"T01","leaf_cluster_id":"C01","owner_agent_id":"W"}],
                    "schedule":[],"staffing":{},"alternatives":[],"open_questions":[]},
                "rules":["Use the actual validated task IDs and unchanged dependency edges.","Exactly one non-master owner per task, including integration and cleanup. Master coordinates/reviews/approves only. Reviewers are read-only.",
                         "Fill cluster, staffing, schedule, constraints and alternatives from real task data; examples are not actual assignments."]}
    raise ValueError("unknown planning stage")
