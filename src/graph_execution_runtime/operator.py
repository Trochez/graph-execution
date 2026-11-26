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


def model_factory(base_url, key, model_id):
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    return OpenAIChatModel(model_id[7:], provider=OpenAIProvider(
        openai_client=provider_client(base_url, key)))


async def approved_bundle(path: Path, key: str):
    b = load_bundle(path)
    available = await discover_models(b["base_url"], key)
    check_approval(b["spec"], load_json(Path(b["approval"])), b["base_url"], available)
    return b


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
        for _ in range(10):
            snap=await self.status()
            if snap["revision"]!=revision or snap["finished"]:return snap
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
        return await self.handle.execute_update(GraphRun.review, {"task": task, "attempt": state["attempt"],
                                                    "action": action, "evidence": evidence})

    async def verify(self, task):
        b = load_bundle(self.bundle_path)
        state = (await self.status())["tasks"][task]
        if state["status"] != "applied":
            raise ValueError("task is not applied")
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
        receipts=await run_checks(Path(b["workspace"]),b["final_checks"])
        result={"passed":all(r["exit_code"]==0 for r in receipts),"checks":receipts,"snapshot":s}
        record=self.project(s)
        atomic_json(record/"final-checks.json",{"passed":result["passed"],"checks":receipts})
        if result["passed"] and b.get("pipeline"):
            Pipeline(Path(b["sources"]["plan"]),Path(b["pipeline"]),Path(b["skill_root"])).finish_executor([record/"execution.json",record/"events.jsonl",record/"final-checks.json"],"Actual configured final checks exited zero; all tasks verified in Temporal")
        return result


async def run_worker(bundle_path: Path, address: str):
    from .activities import Activities
    key = os.environ.get("GEXEC_PROBE_API_KEY","")
    b = await approved_bundle(bundle_path, key)
    spec = b["spec"]
    client = await Client.connect(local_address(address))
    # The process and queue are scoped to exactly one locally authorized bundle.
    model=model_factory(b["base_url"],key,spec["model"])
    acts = Activities(client, Path(b["workspace"]), Path(b["journal"]), spec["model"],
                      lambda task: model,
                      Path(b["skill_root"]), approved_spec=spec, bundle_path=bundle_path)
    async with Worker(client, task_queue=spec["workflow_id"], workflows=[GraphRun,AgentSession],
                      activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready]):
        print(json.dumps({"ready":True,"workflow_id":spec["workflow_id"],"queue":spec["workflow_id"]}),flush=True)
        await asyncio.Future()
