"""Deterministic translation of frozen planning artifacts into exact task scopes.

The compact format is the preferred autonomous interface. Full legacy extensions
remain supported. No model-generated permission or check is silently widened.
"""
from __future__ import annotations
from copy import deepcopy
from .runtime_contract import team_contract,extension_contract,fail
from .parallel_contract import plan_candidates
from .scheduler import conflicts
from .policy import within,safe_path,required_check_indices

def compact_contract(profile,tasks,team):
    rows=tasks["tasks"]
    master,roles,parents,owners=team_contract(rows,team)
    pairs=[(a,b) for a,b in plan_candidates(profile,rows)
           if owners[a]!=owners[b] and roles[owners[a]]==roles[owners[b]]=="worker"]
    return {"master":master,"roles":roles,"parents":parents,"owners":owners,
            "required_root_pairs":pairs,"checks_by_index":profile["checks"],
            "required_peer_handoff":bool(profile.get("required_peer_handoff")),
            "required_checks_by_write_group":profile.get("required_checks_by_write_group",{}),
            "task_write_groups":{t["id"]:t.get("write_scope",[]) for t in rows},
            "rules":["Supply only scopes with reads, writes, check_indices. Inherit hierarchy and scheduled resources.",
                     "Each task selects 1 to 4 approved zero-based check indices.",
                     "Writes must be exact files within the task's planned write groups; read-only tasks cannot write.",
                     "For the required direct HANDOFF, the receiving root must not reserve the sender's concurrently written files; get the contract through the peer message.",
                     "Integration/review may read completed prerequisite outputs."]}

def normalize_extension(profile,tasks,team,submitted):
    if not isinstance(submitted,dict):fail("EXTENSION_FIELDS","Provide an object containing scopes.")
    if set(submitted)!={"scopes"}:
        # Existing full extension remains supported; do not change its declared
        # resources or access automatically.
        extension_contract(profile,tasks,team,submitted)
        return deepcopy(submitted),{"format":"full","narrowed_peer_reads":[]}
    c=compact_contract(profile,tasks,team);rows=tasks["tasks"];scopes=submitted["scopes"]
    if not isinstance(scopes,dict) or set(scopes)!={t["id"] for t in rows}:
        fail("SCOPE_COVERAGE","Provide exactly one scope per validated task.")
    schedule={}
    for entry in team.get("schedule",[]):
        if not isinstance(entry,dict):fail("SCHEDULE_RESOURCES","Invalid frozen schedule entry.")
        k=entry.get("task_id")
        if k not in c["owners"] or entry.get("agent_id",c["owners"][k])!=c["owners"][k]:
            fail("SCHEDULE_OWNER","Frozen schedule task/owner mismatch; team artifact requires correction.")
        resources=entry.get("resources",[])
        if not isinstance(resources,list) or any(type(x)!=str or not x or len(x)>80 for x in resources):
            fail("SCHEDULE_RESOURCES","Frozen schedule resources must be bounded strings.")
        schedule.setdefault(k,set()).update(resources)
    output={"master":c["master"],"roles":c["roles"],"parents":c["parents"],"scopes":{}}
    added_checks=[]
    for t in rows:
        k=t["id"];s=scopes[k]
        if not isinstance(s,dict) or set(s)!={"reads","writes","check_indices"}:
            fail("SCOPE_FIELDS",f"Task {k}: supply reads, writes and check_indices only.")
        idx=s["check_indices"]
        if not isinstance(idx,list) or not 1<=len(idx)<=4 or any(type(i)!=int or not 0<=i<len(profile["checks"]) for i in idx) or len(set(idx))!=len(idx):
            fail("CHECK_INDICES",f"Task {k}: select 1 to 4 unique valid zero-based approved check indices.")
        for field in ("reads","writes"):
            if not isinstance(s[field],list) or any(type(p)!=str for p in s[field]):
                fail("SCOPE_PATH_LIST",f"Task {k}: {field} must contain exact relative file paths.")
        groups=t.get("write_scope",[])
        if not isinstance(groups,list) or any(type(g)!=str for g in groups):
            fail("PLAN_WRITE_GROUPS",f"Task {k}: planned write groups must be a list of paths.")
        groups=[safe_path(g.rstrip("/")) for g in groups]
        if any(not within(p,groups) for p in s["writes"]):
            fail("WRITE_SCOPE_DRIFT",f"Task {k}: writes must be inside its frozen planned write groups; read-only tasks cannot write.")
        if any(not any(within(p,[g]) for p in s["writes"]) for g in groups):
            fail("WRITE_SCOPE_MISSING",f"Task {k}: provide at least one exact output file for each planned write group.")
        mandatory=required_check_indices(profile,s["writes"])
        missing=[i for i in mandatory if i not in idx]
        if len(idx)+len(missing)>4:fail("CHECK_COUNT",f"Task {k}: mandatory and selected checks exceed four; choose a smaller valid set.")
        idx=list(idx)+missing
        if missing:added_checks.append({"task":k,"indices":missing})
        output["scopes"][k]={"reads":list(s["reads"]),"writes":list(s["writes"]),
            "resources":sorted(schedule.get(k,set())),"checks":[profile["checks"][i] for i in idx]}
    # First validate ALL requested paths against approved policy. An unapproved
    # read is never laundered by later narrowing.
    extension_contract(profile,tasks,team,output)
    removed=[]
    if profile.get("required_peer_handoff") and len(c["required_root_pairs"])==1:
        sender,receiver=c["required_root_pairs"][0]
        a,b=output["scopes"][sender],output["scopes"][receiver]
        # The approved contract explicitly requires a live handoff, not a
        # pre-existing file read. Remove only exact receiver reads of paths the
        # sender will write; do not remove ancestor reads or resource locks.
        overlap=set(b["reads"]) & set(a["writes"])
        if overlap:
            b["reads"]=[p for p in b["reads"] if p not in overlap]
            removed=[{"task":receiver,"path":p,"reason":"required_direct_peer_handoff"} for p in sorted(overlap)]
    extension_contract(profile,tasks,team,output)
    return output,{"format":"compact","narrowed_peer_reads":removed,"added_required_checks":added_checks}

def root_priorities(profile,tasks,team,scopes):
    """Give the required pair the first available slots, never waive conflicts."""
    rows=tasks["tasks"]
    pair=profile.get("required_parallel_roots")
    if not pair:return {}
    owner={a["task_id"]:a["owner_agent_id"] for a in team["task_assignments"]}
    # The legacy synthetic fixture may omit planned write groups; derive root
    # candidates from the actual exact compiled paths instead.
    candidates=[{**t,"write_scope":scopes[t["id"]]["writes"]} for t in rows]
    for a,b in sorted(plan_candidates(profile,candidates)):
        x,y=scopes[a],scopes[b]
        if owner[a]==owner[b]:continue
        if set(x["resources"]) & set(y["resources"]):continue
        if any(conflicts(p,q) for p in x["writes"] for q in y["reads"]+y["writes"]):continue
        if any(conflicts(p,q) for p in x["reads"] for q in y["writes"]):continue
        return {a:-1,b:-1}
    return {}
