"""Explicit local run specifications and legacy translations; no inferred approvals."""
from __future__ import annotations

import hashlib
import json
from datetime import date
import re
from pathlib import Path
from urllib.parse import urlsplit

from .scheduler import validate_tasks, normalized


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spec_digest(spec: dict) -> str:
    return hashlib.sha256(json.dumps({k:v for k,v in spec.items() if k!="spec_sha256"},sort_keys=True,separators=(",",":")).encode()).hexdigest()


def prepare(workflow_id: str, plan: Path, tasks_path: Path, team_path: Path, settings: dict) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}",workflow_id):
        raise ValueError("invalid workflow ID")
    tasks_doc, team = load_json(tasks_path), load_json(team_path)
    rows = tasks_doc["tasks"]
    roster = team["agents"]
    assignments = team["task_assignments"]
    agents = {a["id"]: {"role": settings["roles"][a["id"]], "parent": settings["parents"][a["id"]]} for a in roster}
    master = settings["master"]
    if len(agents) != len(roster) or agents.get(master) != {"role": "master", "parent": None}:
        raise ValueError("invalid unique master")
    if sum(a["role"] == "master" for a in agents.values()) != 1:
        raise ValueError("exactly one master")
    for key, a in agents.items():
        if a["role"] not in ("master", "lead", "worker", "reviewer"):
            raise ValueError("unknown role")
        seen = {key}
        p = a["parent"]
        if key != master and p is None:
            raise ValueError("multiple roots")
        while p is not None:
            if p in seen or p not in agents or agents[p]["role"] not in ("master", "lead"):
                raise ValueError("invalid hierarchy")
            seen.add(p)
            p = agents[p]["parent"]
    owner = {a["task_id"]: a["owner_agent_id"] for a in assignments}
    if len(owner) != len(assignments) or set(owner) != {t["id"] for t in rows}:
        raise ValueError("task assignment mismatch")
    tasks = {}
    for t in rows:
        k = t["id"]
        if not isinstance(k,str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}",k):
            raise ValueError("invalid task ID")
        if k in tasks:
            raise ValueError("duplicate task")
        scope = settings["scopes"][k]
        # Exact paths are explicitly supplied by the operator. Never interpret
        # natural-language write_scope as filesystem permission.
        supported={"text_read","text_proposal","peer_message","master_verify","review"}
        if set(t.get("required_capabilities",[]))-supported or t.get("human_gates") or scope.get("unresolved_gates") or scope.get("requires_shell") or scope.get("requires_os_sandbox"):
            raise ValueError("task has unsupported or unresolved mandatory capability")
        checks = t["verification"]
        if isinstance(checks, str):
            checks = [checks]
        if not isinstance(checks, list) or not checks or not all(isinstance(c,str) and c.strip() for c in checks):
            raise ValueError("invalid checks")
        tasks[k] = {"id": k, "owner": owner[k], "dependencies": t.get("depends_on", []),
                    "source": t["source"], "outcome": t["outcome"], "checks": checks,
                    "writes": scope["writes"], "reads": scope["reads"],
                    "resources": scope.get("resources", []), "priority": scope.get("priority", 0),
                    "timeout": scope.get("timeout", 300), "request_budget": scope.get("request_budget", 12)}
        if not 20 <= tasks[k]["timeout"] <= 1800 or not 1 <= tasks[k]["request_budget"] <= 12:
            raise ValueError("invalid task budget")
    validate_tasks(tasks, agents, master)
    capacity = settings.get("capacity", 1)
    run_timeout = settings.get("run_timeout", 7200)
    if type(capacity) is not int or not 1 <= capacity <= 3 or type(run_timeout) is not int or not 60 <= run_timeout <= 7200:
        raise ValueError("invalid run bounds")
    model = settings["model"]
    if not isinstance(model, str) or not model.startswith("openai:") or not model[7:].strip() or "YOUR_" in model.upper():
        raise ValueError("candidate requires explicit OpenAI-compatible provider-qualified model")
    result = {"workflow_id": workflow_id, "tasks": tasks, "agents": agents, "master": master,
            "capacity": capacity, "run_timeout": run_timeout, "model": model,
            "source_hashes": {"plan": fingerprint(plan), "tasks": fingerprint(tasks_path),
                              "team": fingerprint(team_path)}}
    result["spec_sha256"]=spec_digest(result)
    return result


def validate_endpoint(base_url: str):
    u = urlsplit(base_url)
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError("invalid provider endpoint")
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("non-loopback HTTP is not allowed")


def check_approval(spec: dict, approval: dict, base_url: str, available: list[str]):
    validate_endpoint(base_url)
    if (approval.get("model") != spec["model"] or approval.get("base_url") != base_url
            or approval.get("month") != date.today().strftime("%Y-%m")
            or not isinstance(approval.get("confirmation"), str) or not approval["confirmation"].strip()
            or spec["model"][7:] not in available):
        raise PermissionError("current monthly model approval and exact advertised availability required")
