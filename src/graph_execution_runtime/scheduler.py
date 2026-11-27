"""Deterministic scheduler. No I/O, model calls, clock, or vendor imports."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any


def normalized(path: str) -> str:
    if not isinstance(path, str) or not path or len(path) > 512 or "\\" in path or ":" in path:
        raise ValueError("invalid relative path")
    p = PurePosixPath(path)
    if p.is_absolute() or any(x in ("", ".", "..") for x in path.split("/")):
        raise ValueError("path must be normalized and relative")
    if any(x == ".git" or x.startswith(".native-plan-executor") for x in p.parts):
        raise ValueError("runtime and Git internals are reserved")
    return path


def conflicts(left: str, right: str) -> bool:
    return left == right or left.startswith(right + "/") or right.startswith(left + "/")


def ready(tasks: dict, state: dict, cap: int) -> list[str]:
    """Reserve owners, read/write paths and named resources through verification."""
    active = [tasks[k] for k, s in state.items()
              if s["status"] in ("assigned", "in_progress", "verifying", "applying", "applied", "reconciliation_required")]
    result = []
    slots = max(0, cap - sum(s["status"] in ("assigned", "in_progress") for s in state.values()))
    for key in sorted(tasks, key=lambda k: (tasks[k].get("priority", 0), k)):
        t = tasks[key]
        if state[key]["status"] not in ("pending", "ready"):
            continue
        if not all(state[d]["status"] == "done" for d in t["dependencies"]):
            continue
        if t["owner"] in {x["owner"] for x in active}:
            continue
        if any(set(t["resources"]) & set(a["resources"]) or
               any(conflicts(x, y) for x in t["writes"] for y in a["writes"] + a["reads"]) or
               any(conflicts(x, y) for x in t["reads"] for y in a["writes"]) for a in active):
            continue
        if len(result) >= slots:
            break
        active.append(t)
        result.append(key)
    return result


def initialize(tasks: dict) -> dict:
    return {k: {"status": "pending", "attempt": 0, "result": None, "reason": None}
            for k in sorted(tasks)}


def validate_tasks(tasks: dict, agents: dict, master: str):
    if not tasks or len(tasks) > 100 or not agents or len(agents) > 30:
        raise ValueError("task/agent count outside candidate limits")
    if master not in agents:
        raise ValueError("master missing")
    for key, t in tasks.items():
        if not key or t["id"] != key or t["owner"] not in agents or t["owner"] == master:
            raise ValueError("invalid task or worker owner (master implementation unsupported)")
        if len(set(t["dependencies"])) != len(t["dependencies"]) or not set(t["dependencies"]) <= tasks.keys():
            raise ValueError("unknown or duplicate dependency")
        for field in ("writes", "reads"):
            if len(t[field]) > 20 or len(set(t[field])) != len(t[field]):
                raise ValueError("invalid scope")
            for path in t[field]:
                normalized(path)
        if agents[t["owner"]]["role"] == "reviewer" and t["writes"]:
            raise ValueError("reviewer write scope")
        if not t["checks"]:
            raise ValueError("task requires acceptance criteria")
    done = set()
    while len(done) < len(tasks):
        wave = {k for k, t in tasks.items() if k not in done and set(t["dependencies"]) <= done}
        if not wave:
            raise ValueError("dependency cycle")
        done.update(wave)
