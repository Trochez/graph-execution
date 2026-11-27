"""Run-owned subprocesses and bounded shutdown; no global process matching."""
from __future__ import annotations
import asyncio
import json
import os
import re
import signal
import time
from pathlib import Path

async def stop_owned_process(proc,grace=5):
    if proc is None:return
    # All autonomous children are launched in their own POSIX session.
    def send(sig):
        try:os.killpg(proc.pid,sig)
        except ProcessLookupError:pass
    send(signal.SIGTERM)
    try:await asyncio.wait_for(proc.wait(),timeout=grace)
    except asyncio.TimeoutError:
        send(signal.SIGKILL)
        await asyncio.wait_for(proc.wait(),timeout=5)
    # Reap any descendants of the same owned process group.
    send(signal.SIGKILL)

def matching_run(state_root,workspace,plan):
    """Fresh fixture identity must match BOTH resolved input paths."""
    matches=[]
    for p in Path(state_root).glob("gexec-*/run-identity.json"):
        if not re.fullmatch(r"gexec-[a-f0-9]{32}",p.parent.name):continue
        try:
            d=json.loads(p.read_text())
            if d["run_id"]==p.parent.name and Path(d["workspace"]).resolve()==Path(workspace).resolve() and Path(d["original_plan"]).resolve()==Path(plan).resolve():
                matches.append(p.parent)
        except (OSError,ValueError,KeyError,TypeError):continue
    if len(matches)>1:raise RuntimeError("ambiguous qualification run identity")
    return matches[0] if matches else None

def read_terminal(run):
    if run is None:return None
    try:d=json.loads((run/"FINAL_DECISION.json").read_text())
    except (OSError,ValueError):return None
    if d.get("run_id")!=run.name or d.get("records")!=str(run) or d.get("decision") not in ("GO","NO_GO"):
        return None
    return d

def recover_receipt(stdout,run,returncode,watchdog=False):
    """Disk receipt is authoritative evidence, never a substitute for clean exit."""
    disk=read_terminal(run)
    try:stream=json.loads(Path(stdout).read_text())
    except (OSError,ValueError):stream=None
    consistent=disk is not None and isinstance(stream,dict) and stream==disk
    result=dict(disk or {"decision":"NO_GO"})
    if run is not None:result.update(run_id=run.name,records=str(run))
    if not consistent or returncode!=0 or watchdog:result["decision"]="NO_GO"
    return result,{"stdout_matches_terminal":consistent,"terminal_recovered":disk is not None,"watchdog":watchdog}

def remove_run_containers(run_id):
    """Remove only containers labeled by this exact trusted supervisor."""
    if not re.fullmatch(r"gexec-[a-f0-9]{32}",run_id):raise ValueError("invalid container owner")
    from .sandbox import docker
    args=["ps","-aq","--filter","label=io.gexec.run="+run_id]
    ids=docker(args,timeout=8).stdout.decode().split()
    if any(not re.fullmatch(r"[0-9a-f]{12,64}",i) for i in ids):raise ValueError("invalid container ID")
    if ids:docker(["rm","-f",*ids],timeout=15)
    if docker(args,timeout=8).stdout.strip():raise RuntimeError("run containers remain")
    return len(ids)
