"""Shared executable team and scope contract for autonomous Pax.

Model-facing diagnostics contain only fixed messages and validated identifiers.
The compiler and early team gate share the same ownership constraints.
"""
from __future__ import annotations
import re
from .policy import safe_path,within

class RuntimeContractError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)

def fail(code,message):
    raise RuntimeContractError(code,message)

def identifier(v):
    return isinstance(v,str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",v) is not None

def team_contract(rows,team,roles=None,parents=None):
    if not isinstance(team,dict) or not isinstance(team.get("agents"),list) or not isinstance(team.get("task_assignments"),list):
        fail("TEAM_SHAPE","Use an agents array and a task_assignments array.")
    roster=team["agents"]
    if not 1<=len(roster)<=30 or any(not isinstance(a,dict) or not identifier(a.get("id")) for a in roster):
        fail("AGENT_IDS","Use 1 to 30 agents with valid unique identifiers.")
    agents={a["id"]:a for a in roster}
    if len(agents)!=len(roster):fail("AGENT_IDS","Agent identifiers must be unique.")
    declared={k:a.get("role") for k,a in agents.items()}
    if roles is None:roles=declared
    if not isinstance(roles,dict) or set(roles)!=set(agents) or any(r not in ("master","worker","reviewer","lead") for r in roles.values()):
        fail("AGENT_ROLES","Declare one master and supported worker, reviewer or lead roles for every agent.")
    for k,r in declared.items():
        if r is not None and r!=roles[k]:fail("ROLE_DRIFT",f"Agent {k}: the extension role must match the validated roster.")
    masters=[k for k,r in roles.items() if r=="master"]
    if len(masters)!=1:fail("MASTER_COUNT","Declare exactly one coordinator with role master.")
    master=masters[0]
    expected_parents={k:a.get("reports_to",None if k==master else master) for k,a in agents.items()}
    if parents is None:parents=expected_parents
    if not isinstance(parents,dict) or set(parents)!=set(agents):fail("PARENT_COVERAGE","Provide one parent entry per roster agent.")
    for k in agents:
        if "reports_to" in agents[k] and parents[k]!=expected_parents[k]:
            fail("PARENT_DRIFT",f"Agent {k}: preserve the validated reports_to hierarchy.")
        parent=parents[k]
        if k==master:
            if parent is not None:fail("MASTER_PARENT","The master parent must be null.")
            continue
        seen={k}
        while parent is not None:
            if not identifier(parent) or parent not in agents or parent in seen or roles[parent] not in ("master","lead"):
                fail("AGENT_HIERARCHY",f"Agent {k}: use an acyclic parent chain through master or lead agents.")
            seen.add(parent)
            parent=parents[parent]
        if master not in seen:fail("AGENT_HIERARCHY",f"Agent {k}: parent chain must reach the master.")
    ids={r["id"] for r in rows}
    assignments=team["task_assignments"]
    if len(assignments)!=len(ids) or any(not isinstance(a,dict) or not identifier(a.get("task_id")) or not identifier(a.get("owner_agent_id")) for a in assignments):
        fail("ASSIGNMENT_COVERAGE","Assign every validated task exactly once to a roster agent.")
    owners={a["task_id"]:a["owner_agent_id"] for a in assignments}
    if set(owners)!=ids or not set(owners.values())<=set(agents):
        fail("ASSIGNMENT_COVERAGE","Assign every validated task exactly once to an existing roster agent.")
    for row in rows:
        k=row["id"];owner=owners[k]
        if owner==master:
            fail("MASTER_TASK_OWNER",f"Task {k}: master {master} coordinates, reviews and approves only. Assign this task to an eligible non-master agent in team-definition.json and update the team report/schedule. The master cannot execute tasks.")
        if roles[owner]=="reviewer" and row.get("write_scope"):
            fail("REVIEWER_WRITES",f"Task {k}: a reviewer must be read-only; assign write work to a worker.")
    return master,roles,parents,owners

def extension_contract(profile,tasks,team,extension):
    if not isinstance(extension,dict) or set(extension)!={"master","roles","parents","scopes"}:
        fail("EXTENSION_FIELDS","Use exactly master, roles, parents and scopes in the execution extension.")
    rows=tasks["tasks"]
    master,roles,parents,owners=team_contract(rows,team,extension["roles"],extension["parents"])
    if extension["master"]!=master:fail("MASTER_MISMATCH","The extension master must equal the roster master.")
    scopes=extension["scopes"]
    if not isinstance(scopes,dict) or set(scopes)!={r["id"] for r in rows}:
        fail("SCOPE_COVERAGE","Provide exactly one scope per validated task ID.")
    for row in rows:
        k=row["id"];s=scopes[k]
        if not isinstance(s,dict) or set(s)!={"reads","writes","resources","checks"}:
            fail("SCOPE_FIELDS",f"Task {k}: scope requires reads, writes, resources and checks.")
        for field in ("reads","writes"):
            values=s[field]
            if not isinstance(values,list) or len(values)>20 or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):
                fail("SCOPE_PATH_LIST",f"Task {k}: {field} must be a list of at most 20 unique exact relative file paths.")
            for i,v in enumerate(values):
                try:safe_path(v)
                except (ValueError,TypeError):fail("SCOPE_PATH_INVALID",f"Task {k}: {field}[{i}] is not a supported exact relative path.")
                allowed=profile.get("write_paths",profile["paths"]) if field=="writes" else profile["paths"]
                if not within(v,allowed) or not within(v,profile["paths"]):
                    fail("SCOPE_NOT_APPROVED",f"Task {k}: {field}[{i}] is outside the approved project policy. Narrow the scope; never widen authorization.")
        if roles[owners[k]]=="reviewer" and s["writes"]:
            fail("REVIEWER_WRITES",f"Task {k}: reviewer scope must contain no writes.")
        if not isinstance(s["resources"],list) or any(type(x)!=str or len(x)>80 for x in s["resources"]):
            fail("SCOPE_RESOURCES",f"Task {k}: resources must be a list of bounded strings.")
        if not isinstance(s["checks"],list) or not 1<=len(s["checks"])<=4:
            fail("CHECK_COUNT",f"Task {k}: select 1 to 4 exact approved check argv arrays.")
        for i,argv in enumerate(s["checks"]):
            if argv not in profile["checks"]:
                fail("CHECK_NOT_APPROVED",f"Task {k}: checks[{i}] must exactly match one approved argv from gexec_policy. Do not invent or abbreviate commands.")
