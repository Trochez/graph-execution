"""Local operator service. Credentials never appear in spec/workflow payloads."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
from datetime import timedelta
from pathlib import Path

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.worker import Worker
from temporalio.exceptions import WorkflowAlreadyStartedError

from .config import check_approval, fingerprint, load_json, validate_endpoint, spec_digest
from .durable_workflows import GraphRun, AgentSession
from .workspace import snapshot, sha
from .pipeline import Pipeline, atomic_json

def local_address(address):
    if address not in ("localhost:7233", "127.0.0.1:7233", "[::1]:7233"):
        raise ValueError("candidate supports only the trusted local Temporal dev endpoint")
    return address


def load_bundle(path: Path):
    bundle = load_json(path)
    spec = bundle["spec"]
    if spec.get("spec_sha256") != spec_digest(spec):
        raise ValueError("run spec integrity mismatch")
    if set(bundle["sources"])!=set(spec["source_hashes"]):
        raise ValueError("source inventory mismatch")
    for name, filename in bundle["sources"].items():
        if fingerprint(Path(filename)) != spec["source_hashes"][name]:
            raise ValueError("approved source changed: " + name)
    root = Path(bundle["workspace"]).resolve(strict=True)
    journal = Path(bundle["journal"]).resolve()
    if journal.is_relative_to(root):
        raise ValueError("journal must be outside execution workspace")
    if spec.get("runtime_version")==2:
        from .policy import digest,load_profile,compile_settings
        p=load_profile(Path(bundle["profile_path"]),root)
        if digest(p)!=spec["policy_sha256"] or p!=bundle["profile"] or fingerprint(Path(bundle["original_plan"]))!=spec["source_hashes"]["plan"]:
            raise PermissionError("policy or source plan changed")
        ext=load_json(Path(bundle["pipeline"])/"execution-spec.json")
        if digest(ext)!=bundle["extension_sha256"]:raise PermissionError("execution extension changed")
        settings=compile_settings(p,load_json(Path(bundle["sources"]["tasks"])),load_json(Path(bundle["sources"]["team"])),ext)
        if settings["check_commands"]!=bundle["check_commands"] or settings["final_checks"]!=bundle["final_checks"]:
            raise PermissionError("verification policy changed")
    if bundle.get("pipeline"):
        Pipeline(Path(bundle["sources"]["plan"]),Path(bundle["pipeline"]),Path(bundle["skill_root"])).bind(Path(bundle["sources"]["tasks"]),Path(bundle["sources"]["team"]))
    return bundle


def clean_environment():
    # Do not inherit provider secrets into project checks. Project checks are
    # trusted user-approved executable code, not a security sandbox.
    return {k: v for k, v in os.environ.items() if k in (
        "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP",
        "LANG", "LC_ALL", "VIRTUAL_ENV", "PYTHONUTF8")}


async def run_checks(root: Path, commands: list[list[str]]) -> list[dict]:
    if not isinstance(commands, list) or not commands or len(commands) > 8:
        raise ValueError("explicit approved verification commands required")
    receipts = []
    for argv in commands:
        if not isinstance(argv, list) or not argv or not all(isinstance(x,str) and x and len(x)<=2048 for x in argv):
            raise ValueError("invalid approved argv")
        def check():
            try:
                cp = subprocess.run(argv, cwd=root, env=clean_environment(), shell=False,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=90)
                return {"command": argv, "exit_code": cp.returncode,
                        "output_sha256": sha(cp.stdout), "output_bytes": len(cp.stdout)}
            except (OSError, subprocess.TimeoutExpired) as exc:
                return {"command": argv, "exit_code": None, "error": type(exc).__name__}
        receipt = await asyncio.to_thread(check)
        receipts.append(receipt)
        if receipt["exit_code"] != 0:
            break
    return receipts


def provider_client(base_url: str, key: str):
    from openai import AsyncOpenAI
    validate_endpoint(base_url)
    if not key:
        raise ValueError("GEXEC_PROBE_API_KEY is required in the local process environment")
    return AsyncOpenAI(base_url=base_url, api_key=key, max_retries=0, timeout=45)


async def discover_models(base_url, key):
    client = provider_client(base_url, key)
    try:
        page = await client.models.list()
        ids = []
        async for item in page:
            ids.append(item.id)
            if len(ids) > 5000:
                raise ValueError("inventory exceeds bound; inspect manually")
        return sorted(set(ids))
    finally:
        await client.close()


def model_factory(base_url, key, model_id, budget=None):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    if budget is not None:
        import httpx
        from openai import AsyncOpenAI
        validate_endpoint(base_url)
        if not key:raise ValueError("approved local key required")
        client=AsyncOpenAI(base_url=base_url,api_key=key,max_retries=0,timeout=45,
            http_client=httpx.AsyncClient(timeout=45,event_hooks={"request":[budget.on_request],"response":[budget.on_response]}))
    else:client=provider_client(base_url,key)
    return OpenAIChatModel(model_id[7:], provider=OpenAIProvider(openai_client=client))


async def approved_bundle(path: Path, key: str):
    b = load_bundle(path)
    available = await discover_models(b["base_url"], key)
    check_approval(b["spec"], load_json(Path(b["approval"])), b["base_url"], available)
    return b


def compact_status(snap: dict) -> dict:
    """Bound model-facing status; full audit record stays in local projection."""
    tasks={}
    for key,state in snap["tasks"].items():
        task={"status":state["status"],"attempt":state["attempt"]}
        if state["status"] in ("blocked","reconciliation_required","cancelled"):
            task["reason"]=(state.get("reason") or "")[:512]
        if state["status"]=="verifying":
            task["edit_paths"]=(state.get("result") or {}).get("edit_paths",[])
            task["next"]="inspect proposal then explicitly review and verify"
        elif state["status"]=="applied":
            task["next"]="verify"
        tasks[key]=task
    return {"workflow_id":snap["workflow_id"],"revision":snap["revision"],
            "finished":snap["finished"],"cancelled":snap["cancelled"],"tasks":tasks,
            "pending_messages":sum(m["status"]=="ACCEPTED" for m in snap["messages"]),
            "next":"finalize" if snap["finished"] and not snap["cancelled"] and all(t["status"]=="done" for t in tasks.values()) else None}


class Controller:
    def __init__(self, client, bundle_path: Path):
        self.client = client
        self.bundle_path = bundle_path
        self.bundle = load_bundle(bundle_path)
        self.spec = self.bundle["spec"]
        self.handle = client.get_workflow_handle(self.spec["workflow_id"])

    async def start(self):
        b = await approved_bundle(self.bundle_path, os.environ.get("GEXEC_PROBE_API_KEY",""))
        if b["spec"] != self.spec:
            raise ValueError("bundle changed")
        if b.get("pipeline"):
            Pipeline(Path(b["sources"]["plan"]),Path(b["pipeline"]),Path(b["skill_root"])).start_executor(Path(b["sources"]["tasks"]),Path(b["sources"]["team"]))
        # Stable workflow ID; retry start only attaches to existing same-input run.
        try:
            self.handle = await self.client.start_workflow(GraphRun.run, self.spec,
                id=self.spec["workflow_id"], task_queue=self.spec["workflow_id"],
                execution_timeout=timedelta(seconds=self.spec["run_timeout"]+300),
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE)
        except WorkflowAlreadyStartedError:
            snap = await self.status()
            if snap["spec_sha256"] != self.spec["spec_sha256"]:
                raise ValueError("existing workflow belongs to different inputs")
        return await self.status()

    async def status(self):
        snap=await asyncio.wait_for(self.handle.query(GraphRun.snapshot),timeout=20)
        self.project(snap)
        return snap

    def project(self,snap):
        record=Path(self.bundle["journal"])/"records"
        record.mkdir(mode=0o700,parents=True,exist_ok=True)
        atomic_json(record/"execution.json",{"runtime":{"host":"pax","mode":"pax-durable","evidence":["custom agent + Temporal candidate"],"effective_model":"unknown"},"source_hashes":self.spec["source_hashes"],"snapshot":snap})
        import tempfile
        fd,tmp=tempfile.mkstemp(dir=record,prefix=".events-")
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                for event in snap["events"]:f.write(json.dumps(event,sort_keys=True)+"\n")
            os.replace(tmp,record/"events.jsonl")
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        return record

    async def wait(self, revision):
        # Coalesce intermediate scheduling events; return for actionable states.
        for _ in range(20):
            snap=await self.status()
            if snap["finished"] or snap["cancelled"] or any(s["status"] in ("verifying","applied") for s in snap["tasks"].values()):return snap
            if any(m["recipient"]==self.spec["master"] and m["status"]=="ACCEPTED" for m in snap["messages"]):return snap
            await asyncio.sleep(1)
        return snap

    async def proposal(self, task):
        return await self.handle.query(GraphRun.proposal, task)

    async def inbox(self):
        return await self.handle.query(GraphRun.master_inbox)

    async def send(self, recipient, text, message_key, kind="HANDOFF", correlation_id=None):
        mid=sha(f"{self.spec['workflow_id']}:{self.spec['master']}:{message_key}".encode())
        return await self.handle.execute_update(GraphRun.send, {"task":None,"sender":self.spec["master"],"attempt":None,"recipient":recipient,"text":text,"id":mid,"kind":kind,"correlation_id":correlation_id})

    async def ack(self, message_id):
        return await self.handle.execute_update(GraphRun.ack, {"task":None,"sender":self.spec["master"],"attempt":None,"id":message_id})

    async def review(self, task, action, evidence):
        load_bundle(self.bundle_path)
        state = (await self.status())["tasks"][task]
        if self.spec.get("runtime_version")==2 and action=="apply":raise ValueError("digest-bound review required")
        return await self.handle.execute_update(GraphRun.review, {"task": task, "attempt": state["attempt"],
                                                    "action": action, "evidence": evidence})

    async def review_and_verify(self, task, attempt, evidence, proposal_sha256=None):
        """Explicit approval of a previously inspected attempt; never automatic approval."""
        if not isinstance(evidence,str) or not evidence.strip() or len(evidence)>2048:
            raise ValueError("review evidence required")
        load_bundle(self.bundle_path)
        state=(await self.status())["tasks"][task]
        if state["attempt"]!=attempt:
            return {"accepted":False,"reason":"stale attempt"}
        if state["status"]=="verifying":
            r=await self.handle.execute_update(GraphRun.review,{"task":task,"attempt":attempt,
                "action":"apply","evidence":evidence,**({"proposal_sha256":proposal_sha256} if self.spec.get("runtime_version")==2 else {})})
            if not r["accepted"]:return r
        elif state["status"] not in ("applying","applied","done"):
            return {"accepted":False,"reason":"task is not ready for integration"}
        for _ in range(20):
            snap=await self.status()
            state=snap["tasks"][task]
            if state["attempt"]!=attempt or snap["cancelled"]:
                return {"accepted":False,"status":state["status"],"reason":"attempt changed or cancelled"}
            if state["status"]=="done":
                return {"accepted":True,"status":"done","already_verified":True}
            if state["status"]=="applied":
                r=await self.verify(task)
                return {"accepted":True,"verification":r,"status":(await self.status())["tasks"][task]["status"]}
            if state["status"]!="applying":
                return {"accepted":False,"status":state["status"],"reason":state.get("reason")}
            await asyncio.sleep(0.5)
        return {"accepted":True,"status":"applying","next":"wait for durable integration; verify only after applied"}

    async def verify(self, task):
        b = load_bundle(self.bundle_path)
        state = (await self.status())["tasks"][task]
        if state["status"] != "applied":
            raise ValueError("task is not applied")
        if self.spec.get("runtime_version")==2:
            from .coding_tools import stage_for
            from .gitstage import inventory,sha as staged_sha,git
            stage=stage_for(b);record=state["integration"];receipts=record["checks"]
            current=await asyncio.to_thread(inventory,stage.root,stage.head(),stage.profile)
            passed=stage.unchanged() and bool(receipts) and all(r["exit_code"]==0 for r in receipts) and all(staged_sha(current.get(f["path"]))==f["sha256"] for f in record["files"])
            evidence=json.dumps({"commit":record["new"],"independent_checks_passed":passed,"receipt_hash":sha(json.dumps(receipts,sort_keys=True).encode())})
            response=await self.handle.execute_update(GraphRun.verify,{"task":task,"attempt":state["attempt"],"passed":passed,"evidence":evidence})
            if passed and response.get("accepted") and os.environ.get("GEXEC_QUALIFICATION_FAULT_CONTROL"):
                from .faults import barrier
                await asyncio.to_thread(barrier,"master",self.spec["workflow_id"],{"pid":os.getpid(),"task":task,"commit":record["new"]})
            return {"decision":response,"checks":receipts}
        root = Path(b["workspace"])
        files = state["integration"]["files"]
        if any(snapshot(root, f["path"])[0] != f["sha256"] for f in files):
            return await self.handle.execute_update(GraphRun.verify, {"task":task,"attempt":state["attempt"],
                "passed":False,"evidence":"integrated file hashes changed"})
        receipts = await run_checks(root, b["check_commands"][task])
        passed = all(r["exit_code"] == 0 for r in receipts)
        passed = passed and all(snapshot(root,f["path"])[0] == f["sha256"] for f in files)
        # Keep output and credentials out of history; evidence of actual exits and hashes.
        evidence = json.dumps({"checks":[{"exit_code":r["exit_code"],"output_sha256":r.get("output_sha256")}
                                        for r in receipts],"integrated_hashes_match":passed},sort_keys=True)
        response = await self.handle.execute_update(GraphRun.verify, {"task":task,"attempt":state["attempt"],
                                "passed":passed,"evidence":evidence})
        return {"decision":response,"checks":receipts}

    async def stop(self, reason):
        await self.handle.signal(GraphRun.stop, reason)
        return {"stop_requested":True, "note":"bounded active operations must drain; no rollback promised"}

    async def finalize(self):
        b=load_bundle(self.bundle_path)
        s=await self.status()
        if not s["finished"] or s["cancelled"] or any(t["status"]!="done" for t in s["tasks"].values()):
            raise ValueError("all tasks must finish verified")
        if self.spec.get("runtime_version")==2:
            from .coding_tools import stage_for,checks_in_sandbox,compact_receipts
            from .gitstage import inventory
            st=stage_for(b);head=st.head()
            if not st.unchanged():raise PermissionError("original checkout changed")
            receipts=compact_receipts(await asyncio.to_thread(checks_in_sandbox,inventory(st.root,head,st.profile),st.profile,b["final_checks"],final=True))
            if not st.unchanged() or st.head()!=head:raise PermissionError("checkout or staging ref changed during final verification")
        else:receipts=await run_checks(Path(b["workspace"]),b["final_checks"])
        result={"passed":bool(receipts) and all(r["exit_code"]==0 for r in receipts),"checks":receipts,"snapshot":s}
        record=self.project(s)
        atomic_json(record/"final-checks.json",{"passed":result["passed"],"checks":receipts,**({"commit":head} if self.spec.get("runtime_version")==2 else {})})
        if result["passed"] and b.get("pipeline"):
            Pipeline(Path(b["sources"]["plan"]),Path(b["pipeline"]),Path(b["skill_root"])).finish_executor([record/"execution.json",record/"events.jsonl",record/"final-checks.json"],"Actual configured final checks exited zero; all tasks verified in Temporal")
        return result


async def run_worker(bundle_path: Path, address: str, ready_event=None):
    from .activities import Activities
    key = os.environ.get("GEXEC_PROBE_API_KEY","")
    b = await approved_bundle(bundle_path, key)
    spec = b["spec"]
    client = await Client.connect(local_address(address))
    # The process and queue are scoped to exactly one locally authorized bundle.
    routes={name:model_factory(b["base_url"],key,name) for name in set(spec.get("agent_models",{}).values())|{spec["model"]}}
    def route(task):
        name=spec.get("agent_models",{}).get(task["owner"],spec["model"])
        if spec.get("runtime_version")==2:
            from .budget import Budget
            return model_factory(b["base_url"],key,name,Budget(b["budget_db"],task["id"],task["request_budget"]))
        return routes[name]
    acts = Activities(client, Path(b["workspace"]), Path(b["journal"]), spec["model"],
                      route,
                      Path(b["skill_root"]), approved_spec=spec, bundle_path=bundle_path)
    async with Worker(client, task_queue=spec["workflow_id"], workflows=[GraphRun,AgentSession],
                      activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready]):
        if ready_event is not None:ready_event.set()
        else:print(json.dumps({"ready":True,"workflow_id":spec["workflow_id"],"queue":spec["workflow_id"]}),flush=True)
        await asyncio.Future()
