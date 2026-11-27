"""Optional operator-authorized parallel/reviewer topology requirements."""
from .scheduler import conflicts,ready,initialize

class ParallelContractError(ValueError):pass
def path_hits(paths,target):
    return any(isinstance(p,str) and conflicts(p.rstrip("/"),target) for p in paths)
def ancestors(rows,k):
    todo=list(rows[k].get("depends_on",[]));seen=set()
    while todo:
        a=todo.pop()
        if a in seen or a not in rows:continue
        seen.add(a);todo.extend(rows[a].get("depends_on",[]))
    return seen
def plan_candidates(profile,rows):
    pair=profile.get("required_parallel_roots",[])
    if not pair:return []
    roots=[t for t in rows if not t.get("depends_on",[])]
    pairs=[(a["id"],b["id"]) for a in roots for b in roots if a["id"]!=b["id"]
           and path_hits(a.get("write_scope",[]),pair[0]) and path_hits(b.get("write_scope",[]),pair[1])
           and not any(conflicts(x.rstrip("/"),y.rstrip("/")) for x in a.get("write_scope",[]) for y in b.get("write_scope",[]) if isinstance(x,str) and isinstance(y,str))]
    if not pairs:raise ParallelContractError("Required independent root tasks are missing. Keep the two approved path groups in separate root tasks with disjoint writes; a live peer handoff is not a completion dependency.")
    return pairs
def review_candidates(profile,rows):
    if not profile.get("require_independent_review"):return []
    byid={t["id"]:t for t in rows};writers={t["id"] for t in rows if t.get("write_scope",[])}
    candidates=[t["id"] for t in rows if not t.get("write_scope",[]) and writers and writers<=ancestors(byid,t["id"])]
    if not candidates:raise ParallelContractError("An independent read-only review task must follow all implementation writes. Separate deletion/cleanup from the reviewer.")
    return candidates
def check_plan(profile,rows):
    plan_candidates(profile,rows);review_candidates(profile,rows)
def check_team(profile,rows,team):
    pairs=plan_candidates(profile,rows);reviews=review_candidates(profile,rows)
    if not pairs and not reviews:return
    owners={a["task_id"]:a["owner_agent_id"] for a in team["task_assignments"]}
    roles={a["id"]:a.get("role") for a in team["agents"]}
    if pairs and not any(owners[a]!=owners[b] and roles.get(owners[a])=="worker" and roles.get(owners[b])=="worker" for a,b in pairs):
        raise ParallelContractError("Assign the two independent root tasks to distinct worker agents.")
    if reviews and not any(roles.get(owners[k])=="reviewer" and owners[k] not in {owners[t["id"]] for t in rows if t.get("write_scope",[])} for k in reviews):
        raise ParallelContractError("Assign the downstream read-only review to an independent reviewer agent.")
def check_spec(profile,spec):
    pair=profile.get("required_parallel_roots",[])
    tasks=spec["tasks"];agents=spec["agents"]
    if pair:
        initial=ready(tasks,initialize(tasks),profile["capacity"])
        if not any(a!=b and tasks[a]["owner"]!=tasks[b]["owner"] and
                   agents[tasks[a]["owner"]]["role"]==agents[tasks[b]["owner"]]["role"]=="worker" and
                   path_hits(tasks[a]["writes"],pair[0]) and path_hits(tasks[b]["writes"],pair[1])
                   for a in initial for b in initial):
            raise ParallelContractError("Compiled root tasks cannot launch concurrently: use distinct owners, disjoint writes/reads and no conflicting resource reservation for the two approved path groups.")
    if profile.get("require_independent_review"):
        rows={k:{"depends_on":t["dependencies"]} for k,t in tasks.items()}
        writers={k for k,t in tasks.items() if t["writes"]}
        if not any(not t["writes"] and agents[t["owner"]]["role"]=="reviewer" and writers<=ancestors(rows,k) for k,t in tasks.items()):
            raise ParallelContractError("Compiled plan requires a downstream independent read-only reviewer.")
