"""Pax-only autonomous local runner. Model approval and profile setup are one-time inputs."""
from __future__ import annotations
import argparse
import asyncio
import getpass
import json
import os
import re
import signal
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

from .cli import private_json
from .config import fingerprint,load_json,check_approval
from .policy import validate_profile,load_profile,profile_path,digest
from .gitstage import inspect,inventory,Staging
from .pipeline import Pipeline,atomic_json
from .budget import Budget

def state_root():
    return Path.home()/".local/state/graph-execution/runs"

def run_path(run_id):
    if not re.fullmatch(r"gexec-[a-f0-9]{32}",run_id):raise ValueError("invalid run ID")
    return state_root()/run_id

def setup(args):
    root=args.workspace.resolve(strict=True);inspect(root)
    p=validate_profile(load_json(args.profile),root)
    target=profile_path(root)
    private_json(target,p)
    return {"profile":str(target),"sha256":digest(p),"status":"configured"}

def terminal(path,result):
    out=path/"FINAL_DECISION.json"
    # No success without actual final receipt; one immutable terminal decision.
    private_json(out,result)
    return result

async def execute(args):
    from .operator import discover_models,local_address,Controller
    from .process_control import stop_owned_process,remove_run_containers
    from .sandbox import Sandbox
    from temporalio.client import Client
    from temporalio.service import RPCError
    root=args.workspace.resolve(strict=True);original=args.plan.resolve(strict=True)
    if original.suffix.lower()!=".md" or original.stat().st_size>262144:raise ValueError("bounded Markdown required")
    original.read_text(encoding="utf-8")
    run_id="gexec-"+uuid4().hex;run=run_path(run_id)
    if run.resolve().is_relative_to(root):raise ValueError("run records must be outside workspace")
    run.mkdir(mode=0o700,parents=True,exist_ok=False)
    private_json(run/"run-identity.json",{"run_id":run_id,"workspace":str(root),"original_plan":str(original)})
    os.environ["GEXEC_SANDBOX_RUN_ID"]=run_id
    result={"run_id":run_id,"decision":"NO_GO","stage":"preflight","effective_model":"unknown"}
    worker=None;process=None;client=None;bundle_path=run/"bundle.json";controller=None
    stage=None;budget=Budget(run/"budget.db","master",60)
    key=os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
    os.environ["GEXEC_PROBE_API_KEY"]=key
    restart=0
    stop_requested=False
    async def stop_process():
        await stop_owned_process(process)
    async def ensure_worker():
        nonlocal worker
        if worker is not None:
            if worker.returncode is not None:raise RuntimeError("dedicated worker exited")
            return
        if not bundle_path.exists():raise RuntimeError("worker bundle missing")
        output=run/"worker.stdout"
        with output.open("wb") as out,(run/"worker.stderr").open("wb") as err:
            worker=await asyncio.create_subprocess_exec(sys.executable,"-m","graph_execution_runtime.cli","worker","--bundle",str(bundle_path),
                cwd=run,env=dict(os.environ,PYTHON_DOTENV_DISABLED="1"),stdout=out,stderr=err,start_new_session=True)
        atomic_json(run/"worker-process.json",{"pid":worker.pid,"workflow_id":run_id})
        deadline=asyncio.get_running_loop().time()+35
        while asyncio.get_running_loop().time()<deadline:
            if worker.returncode is not None:raise RuntimeError("worker exited before readiness")
            for line in output.read_text(errors="replace").splitlines():
                try:r=json.loads(line)
                except ValueError:continue
                if isinstance(r,dict) and r.get("ready") is True and r.get("workflow_id")==run_id and r.get("queue")==run_id:
                    atomic_json(run/"worker-ready.json",{"ready":True,"workflow_id":run_id})
                    return
            await asyncio.sleep(.2)
        raise TimeoutError("worker readiness timeout")
    async def supervise():
        nonlocal process,restart,controller,stage,stop_requested
        p=load_profile(profile_path(root),root);baseline=inspect(root)
        result.update(baseline=baseline,requested_model=p["model"])
        if sys.version_info[:2]!=(3,12):raise RuntimeError("Python 3.12 required")
        from importlib.metadata import version
        if version("pydantic-ai-pax")!="0.74.0":raise RuntimeError("Pax 0.74.0 required")
        route=p["model"];ids=await discover_models(p["base_url"],key)
        check_approval({"model":route},load_json(Path(p["approval"])),p["base_url"],ids)
        with tempfile.TemporaryDirectory(prefix="gexec-preflight-") as scratch:
            def probe():
                with Sandbox(scratch,p) as sb:
                    a=sb.run(["python","-c","import os,sys; assert os.getuid()!=0 and sys.version_info[:2]==(3,12); open('probe.txt','w').write('ok')"])
                    if a["exit_code"]!=0:raise RuntimeError("Docker non-root scratch probe failed")
                    if p["wheels"] and sb.install(sorted(p["wheels"]))["exit_code"]!=0:raise RuntimeError("offline installation probe failed")
            await asyncio.to_thread(probe)
        plan=run/"PLAN.md";plan.write_bytes(original.read_bytes());plan.chmod(0o600)
        data=inventory(root,baseline["head"],p)
        planning={"run_id":run_id,"plan":str(plan),"original_plan":str(original),"workspace":str(root),
            "skill_root":p["skill_root"],"run_dir":str(run),"base_url":p["base_url"],"model":route,
            "read_paths":sorted(data),"profile":p,"profile_path":str(profile_path(root)),"policy_sha256":digest(p),"baseline":baseline}
        private_json(run/"planning.json",planning)
        private_json(run/"manifest.json",{"run_id":run_id,"baseline":baseline,"plan_sha256":fingerprint(plan),
            "policy_sha256":digest(p),"model":route,"timeout":p["timeout"]})
        stage=Staging(root,p,run_id,baseline,run/"journal/publication");stage.start()
        px=Path(sys.executable).parent/("pax.exe" if os.name=="nt" else "pax")
        if not px.is_file():raise RuntimeError("Pax not installed in runtime environment")
        env=dict(os.environ,GEXEC_RUN_BUNDLE=str(bundle_path),GEXEC_PIPELINE_CONFIG=str(run/"planning.json"),
                 GEXEC_TEMPORAL_ADDRESS="localhost:7233",PYTHON_DOTENV_DISABLED="1",PYDANTIC_AI_NO_BANNER="1")
        from .master_phases import run_phases
        pipe=Pipeline(plan,run,Path(p["skill_root"]))
        def record_phase(phase,attempt,recovered):
            nonlocal restart
            restart=recovered
            result["stage"]="master_"+phase
            atomic_json(run/"master-phase.json",{"phase":phase,"attempt":attempt,"restarts":recovered})
        async def launch(phase,attempt,limit,prompt):
            nonlocal process,stop_requested
            # Keep the execution master PID naming stable for the L02 harness;
            # normal planning phase transitions are not fault recoveries.
            tag=str(attempt) if phase=="execute" else phase+"-"+str(attempt)
            log=run/f"pax-{tag}.log"
            fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,"wb") as stream:
                phase_env=dict(env,GEXEC_MASTER_PHASE=phase)
                process=await asyncio.create_subprocess_exec(str(px),"--agent","graph_execution_runtime.pax_bridge:agent",
                    "--database",str(run/f"pax-{tag}.db"),"--request-limit",str(limit),"-p",prompt,
                    cwd=run,env=phase_env,stdout=stream,stderr=asyncio.subprocess.STDOUT,start_new_session=True)
                atomic_json(run/f"master-{tag}.json",{"pid":process.pid,"generation":attempt,"phase":phase,"request_cap":limit})
                while process.returncode is None:
                    if (run/"cancel.request").exists():
                        stop_requested=True;raise RuntimeError("operator cancellation")
                    if phase=="execute":await ensure_worker()
                    try:await asyncio.wait_for(process.wait(),timeout=.5)
                    except asyncio.TimeoutError:pass
            atomic_json(run/f"master-exit-{tag}.json",{"phase":phase,"attempt":attempt,"exit_code":process.returncode})
            await stop_process()
        def remaining():
            return 60-budget.summary()["requests_by_actor"].get("master",0)
        async with asyncio.timeout(max(1,p["timeout"]-90)):
            restart=await run_phases(pipe,bundle_path,run/"journal/records/final-checks.json",launch,remaining,record_phase)
            result["stage"]="final_verification"
            controller=Controller(client,bundle_path)
            s=await controller.status()
            f=load_json(run/"journal/records/final-checks.json")
            stages=Pipeline(plan,run,Path(p["skill_root"])).read()["stages"]
            if (not s["finished"] or s["cancelled"] or any(t["status"]!="done" for t in s["tasks"].values())
                or not f["passed"] or f["commit"]!=stage.head() or not stage.unchanged()
                or any(v["status"]!="completed" for v in stages.values()) or stage.head()==baseline["head"]
                or fingerprint(original)!=fingerprint(plan)):
                raise RuntimeError("terminal verification predicate failed")
            result.update(decision="GO",stage="completed",implementation_ref=stage.ref,implementation_commit=stage.head(),
                          tasks={k:v["status"] for k,v in s["tasks"].items()},peer_ack=any(m["status"]=="PROCESSED" for m in s["messages"]),
                          final_checks=True,original_unchanged=True,workflow_id=s["workflow_id"])
    loop=asyncio.get_running_loop();current=asyncio.current_task()
    loop.add_signal_handler(signal.SIGTERM,current.cancel)
    try:
        client=await asyncio.wait_for(Client.connect(local_address("localhost:7233")),timeout=20)
        if not await asyncio.wait_for(client.service_client.check_health(),timeout=10):raise RuntimeError("Temporal unhealthy")
        await supervise()
    except (Exception,KeyboardInterrupt,asyncio.CancelledError) as exc:
        result.update(decision="NO_GO",error_type=type(exc).__name__)
        if (run/"master-phase.json").is_file():result["master_phase"]=load_json(run/"master-phase.json")
        if (run/"compile-validation.json").is_file():result["compile_validation"]=load_json(run/"compile-validation.json")
        if (run/"planning-validation.json").is_file():
            result["planning_validation"]=load_json(run/"planning-validation.json")
    finally:
        # Cleanup stages are independent: failure to drain a workflow must not
        # skip stopping the dedicated worker or removing run-owned containers.
        cleanup={}
        async def step(name,fn):
            try:cleanup[name]=await fn()
            except Exception as exc:cleanup[name]={"error":type(exc).__name__}
        async def stop_master():
            await stop_process();return {"stopped":True}
        await step("master",stop_master)
        async def stop_workflow():
            if not bundle_path.exists() or client is None:return {"status":"not_started"}
            if result["decision"]=="GO":return {"status":"verified_complete"}
            handle=client.get_workflow_handle(run_id)
            try:
                desc=await asyncio.wait_for(handle.describe(),timeout=5)
                status=desc.status.name if desc.status else "UNKNOWN"
                if status=="RUNNING":
                    try:
                        from .durable_workflows import GraphRun
                        await asyncio.wait_for(handle.signal(GraphRun.stop,"supervisor terminal failure"),timeout=5)
                        await asyncio.wait_for(handle.result(),timeout=10)
                    except Exception:
                        # Only this run's workflow; never reset the namespace or
                        # cancel unrelated work. Preserve an explicit forced-stop receipt.
                        await asyncio.wait_for(handle.terminate(reason="bounded supervisor cleanup"),timeout=5)
                    desc=await asyncio.wait_for(handle.describe(),timeout=5)
                    status=desc.status.name if desc.status else "UNKNOWN"
                if status in ("RUNNING","UNKNOWN"):raise RuntimeError("workflow stop unconfirmed")
                # Best effort final snapshot while the dedicated worker exists.
                try:await asyncio.wait_for(Controller(client,bundle_path).status(),timeout=3)
                except Exception:pass
                return {"status":status}
            except RPCError as exc:
                if exc.status.name=="NOT_FOUND":return {"status":"not_started"}
                raise
        await step("workflow",stop_workflow)
        async def stop_worker():
            await stop_owned_process(worker);return {"stopped":True}
        await step("worker",stop_worker)
        async def stop_containers():
            # Bounded synchronous Docker calls: no executor threads left behind.
            return {"removed":remove_run_containers(run_id)}
        await step("containers",stop_containers)
        result["cleanup"]=cleanup
        if any("error" in x for x in cleanup.values()):
            result.update(decision="NO_GO",cleanup_error="incomplete_cleanup")
        loop.remove_signal_handler(signal.SIGTERM)
        result["master_restarts"]=restart
        try:result["budget"]=budget.summary()
        except Exception as exc:result.update(decision="NO_GO",budget_error=type(exc).__name__)
        result["records"]=str(run)
        if stage:result["implementation_ref"]=stage.ref
        terminal(run,result)
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);s=p.add_subparsers(dest="command",required=True)
    m=s.add_parser("setup");m.add_argument("--workspace",type=Path,required=True);m.add_argument("--profile",type=Path,required=True)
    m=s.add_parser("run");m.add_argument("--plan",type=Path,required=True);m.add_argument("--workspace",type=Path,required=True)
    for cmd in ("status","cancel"):
        m=s.add_parser(cmd);m.add_argument("--run-id",required=True)
    a=p.parse_args()
    try:
        if a.command=="setup":r=setup(a)
        elif a.command=="run":r=asyncio.run(execute(a))
        else:
            path=run_path(a.run_id)
            if not path.is_dir():raise ValueError("unknown run")
            if (path/"FINAL_DECISION.json").exists():r=load_json(path/"FINAL_DECISION.json")
            elif a.command=="cancel":
                if not (path/"cancel.request").exists():private_json(path/"cancel.request",{"requested":True})
                r={"cancel_requested":True}
            else:r={"status":"running_or_interrupted","manifest":load_json(path/"manifest.json")}
        print(json.dumps(r,indent=2,sort_keys=True));return 2 if r.get("decision")=="NO_GO" else 0
    except (Exception,KeyboardInterrupt) as exc:
        print(json.dumps({"decision":"NO_GO","error_type":type(exc).__name__}));return 2
