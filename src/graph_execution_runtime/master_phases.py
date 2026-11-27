"""Deterministic master phase routing: checkpoints, not model text, authorize progress."""
from __future__ import annotations
from .pipeline import PLAN,TEAM,EXEC
from .config import load_json

PHASES=("plan","team","prepare","execute")
SKILLS={"plan":("gexec",PLAN),"team":(TEAM,),"prepare":(EXEC,),"execute":(EXEC,)}
COMMON={"gexec_runtime_info","gexec_load_skill","gexec_pipeline_init","gexec_skill_reference"}
PLAN_TOOLS={"gexec_plan_source","gexec_inventory","gexec_policy","gexec_planning_read","gexec_stage_begin","gexec_stage_write","gexec_stage_read","gexec_stage_finish","gexec_stage_fail","gexec_stage_contract"}
TOOLS={
    "plan":COMMON|PLAN_TOOLS,
    "team":COMMON|PLAN_TOOLS,
    "prepare":COMMON|{"gexec_plan_source","gexec_inventory","gexec_policy","gexec_stage_read","gexec_prepare_autonomous"},
    "execute":COMMON|{"gexec_start","gexec_status","gexec_read_input","gexec_proposal","gexec_review_and_verify","gexec_review","gexec_verify","gexec_wait","gexec_inbox","gexec_message","gexec_ack","gexec_finalize","gexec_cancel"}}
def stage_summary(s):
    return {"active_stage":s["active_stage"],"stages":{k:v["status"] for k,v in s["stages"].items()}}

def next_phase(pipe,bundle,final):
    s=pipe.init();st=s["stages"]
    for index,name in enumerate((PLAN,TEAM,EXEC)):
        if st[name]["status"]=="blocked":raise RuntimeError("planning or execution stage blocked")
        if st[name]["status"]=="completed":
            # Check both predecessor inputs and this stage's output fingerprints.
            pipe.gate._inputs(s,index+1)
        elif name==PLAN:return "plan"
        elif name==TEAM:return "team"
        else:return "execute" if bundle.is_file() else "prepare"
    if not bundle.is_file() or not final.is_file() or not load_json(final).get("passed"):
        raise RuntimeError("completed execution lacks final receipt")
    return None

def prompt_for(phase,recover=False):
    prefix=("Recover only this phase from its durable artifacts; never regenerate completed stages. " if recover else "")
    common="You are the same logical Pax master, in a fresh context for one phase only. Use the actual named skills and approved tools. Never claim success without the deterministic checkpoint. "
    specific={
        "plan":"Load gexec and critical-path-planner using gexec_load_skill. Read the original plan, policy, inventory and relevant files. Call gexec_stage_begin for critical-path-planner (idempotent). Create backlog.md and tasks.json with actual common top-level unit and numeric durations. Preserve explicitly independent work: a live peer HANDOFF is communication within concurrent tasks, not a completed-task dependency. Combine same-owner mechanical steps when appropriate. Honor any required_parallel_roots and independent review policy. Use the stage schema and call gexec_stage_finish. If repair_required correct once; blocked means stop. Inspect the deterministic analysis, then return a short final response. Do not begin team design.",
        "team":"Load backlog-team-designer. Read the completed critical-path-planner tasks.json and dag-analysis.json using gexec_stage_read, plus policy and source as needed. Begin backlog-team-designer. Preserve the validated DAG; honor required concurrent root owners, capacity and independent read-only review when specified. Create all three team artifacts and finish the gate. Correct repair_required once; stop on blocked. Inspect graph-analysis.json then return a short final response. Do not compile or launch execution.",
        "prepare":"Load native-plan-executor and read gexec_skill_reference('pax-protocol'). Read the validated tasks.json and team-definition.json, approved inventory and policy. Compile the exact extension through gexec_prepare_autonomous. A peer handoff must not be replaced by an artificial serial dependency or conflicting scheduler read/write reservation. Preserve approved checks, distinct owners, and read-only reviewer. Correct any structured repair_required once. Stop when prepared; do not start execution.",
        "execute":"Load native-plan-executor, read gexec_skill_reference('pax-protocol'), and inspect gexec_runtime_info. The execution bundle is already validated and the worker is supervised. Call gexec_start to attach or start, then inspect status. Inspect each proposal with gexec_proposal before explicit gexec_review_and_verify; use gexec_verify only for applied tasks. Use gexec_wait for pending work instead of repeated polling. Acknowledge relevant messages. Once all tasks are done, call gexec_finalize and return a short final response. Never recreate planning artifacts or the bundle."}
    return prefix+common+specific[phase]

async def run_phases(pipe,bundle,final,launch,remaining,record):
    """launch(phase,attempt,limit,prompt) is one real Pax subprocess.
    Phase completion is determined by durable receipts, even if the process
    exits nonzero after writing them. At most one recovery across all phases.
    """
    recovered=0
    attempts={}
    while True:
        phase=next_phase(pipe,bundle,final)
        if phase is None:return recovered
        count=attempts.get(phase,0)+1
        attempts[phase]=count
        if count>1:
            if recovered:raise RuntimeError("master recovery exhausted")
            recovered=1
        cap=min(40 if phase=="execute" and count==1 else 20 if phase=="execute" else 16,remaining())
        if cap<=0:raise RuntimeError("master request budget exhausted")
        record(phase,count,recovered)
        await launch(phase,count,cap,prompt_for(phase,count>1))
        validation=pipe.run_dir/"planning-validation.json"
        if validation.is_file() and any(v.get("terminal") for v in load_json(validation).values()):
            raise RuntimeError("focused planning repair exhausted")
        compilation=pipe.run_dir/"compile-validation.json"
        if compilation.is_file() and load_json(compilation).get("status")=="blocked":raise RuntimeError("scope compilation repair exhausted")
        # Never infer phase progress from exit status or prose.
        after=next_phase(pipe,bundle,final)
        if after==phase and recovered:raise RuntimeError("master did not complete within bounded recovery")
