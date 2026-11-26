"""Explicit operator commands for the experimental Pax runtime."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import date
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from .config import load_json, prepare, validate_endpoint


def private_json(path, data):
    p=Path(path).expanduser()
    p.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,"w",encoding="utf-8") as f:
        json.dump(data,f,indent=2,sort_keys=True); f.write("\n")


def approval_path():
    return Path.home()/".config/graph-execution/pax/model-policy.json"


async def execute(args):
    from .operator import (Controller, discover_models, local_address, run_worker)
    from temporalio.client import Client
    if args.command=="models":
        key=os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
        return {"coverage":"advertised endpoint only","models":await discover_models(args.base_url,key)}
    if args.command=="approve-model":
        key=os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
        ids=await discover_models(args.base_url,key)
        if not args.model.startswith("openai:") or args.model[7:] not in ids:
            raise ValueError("model not in endpoint inventory")
        if args.confirmation != args.model:
            raise ValueError("explicit --confirmation must equal the exact approved provider-qualified ID")
        # Never overwrite prior approvals silently: archive by explicit operator action.
        private_json(args.output,{"model":args.model,"base_url":args.base_url,
            "month":date.today().strftime("%Y-%m"),"confirmation":args.confirmation,
            "inventory_coverage":"advertised endpoint only"})
        return {"approved":args.model,"path":str(args.output)}
    if args.command=="prepare":
        settings=load_json(args.settings)
        if settings.get("acknowledge_trusted_local_namespace") is not True:
            raise ValueError("operator must acknowledge trusted local dev namespace and source-in-history scope")
        root=args.workspace.resolve(strict=True)
        skill_root=args.skill_root.resolve(strict=True)
        journal=args.journal.resolve()
        if journal.is_relative_to(root):
            raise ValueError("journal must be outside workspace")
        validate_endpoint(settings["base_url"])
        spec=prepare(args.run_id or ("gexec-"+uuid4().hex),args.plan,args.tasks,args.team,settings)
        if set(settings["check_commands"])!=set(spec["tasks"]) or not settings["final_checks"]:
            raise ValueError("explicit checks required for all tasks and final integrated check")
        if args.pipeline:
            from .pipeline import Pipeline
            Pipeline(args.plan,args.pipeline,skill_root).bind(args.tasks,args.team)
        private_json(args.output,{"spec":spec,"pipeline":str(args.pipeline.resolve()) if args.pipeline else None,"workspace":str(root),"skill_root":str(skill_root),
            "journal":str(journal),"base_url":settings["base_url"],"approval":str(args.approval.resolve()),
            "check_commands":settings["check_commands"],"final_checks":settings["final_checks"],
            "sources":{"plan":str(args.plan.resolve()),"tasks":str(args.tasks.resolve()),"team":str(args.team.resolve())}})
        return {"prepared":str(args.output),"workflow_id":spec["workflow_id"]}
    if args.command=="doctor":
        c=await Client.connect(local_address(args.address))
        return {"temporal_connected":bool(c),"versions":{p:version(p) for p in
            ["pydantic-ai-pax","pydantic-ai-harness","pydantic-graph","temporalio","graph-execution-runtime"]},
            "qualification":"candidate; live native host matrix not inferred"}
    if args.command=="worker":
        await run_worker(args.bundle,args.address)
        return {}
    client=await Client.connect(local_address(args.address))
    controller=Controller(client,args.bundle)
    if args.command=="start": return await controller.start()
    if args.command=="status": return await controller.status()
    if args.command=="review": return await controller.review(args.task,args.action,args.evidence)
    if args.command=="verify": return await controller.verify(args.task)
    if args.command=="cancel": return await controller.stop(args.reason)
    if args.command=="finalize": return await controller.finalize()
    raise ValueError("unsupported command")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--address",default="localhost:7233")
    s=p.add_subparsers(dest="command",required=True)
    m=s.add_parser("models");m.add_argument("--base-url",required=True)
    m=s.add_parser("approve-model")
    m.add_argument("--base-url",required=True);m.add_argument("--model",required=True)
    m.add_argument("--confirmation",required=True);m.add_argument("--output",type=Path,default=approval_path())
    m=s.add_parser("prepare")
    for key in ("plan","tasks","team","settings","workspace","skill-root","journal","output"):
        m.add_argument("--"+key,type=Path,required=True)
    m.add_argument("--approval",type=Path,default=approval_path());m.add_argument("--run-id")
    mode=m.add_mutually_exclusive_group(required=True);mode.add_argument("--pipeline",type=Path);mode.add_argument("--standalone",action="store_true")
    s.add_parser("doctor")
    for command in ("worker","start","status","review","verify","cancel","finalize"):
        m=s.add_parser(command);m.add_argument("--bundle",required=True,type=Path)
        if command in ("review","verify"):m.add_argument("--task",required=True)
        if command=="review":
            m.add_argument("--action",choices=("apply","repair","block"),required=True)
            m.add_argument("--evidence",required=True)
        if command=="cancel":m.add_argument("--reason",required=True)
    args=p.parse_args()
    try:
        result=asyncio.run(execute(args))
        print(json.dumps(result,sort_keys=True,indent=2))
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        # No provider bodies/headers/credentials in logs.
        print(json.dumps({"error_type":type(exc).__name__,"status":"BLOCKED"}),file=sys.stderr)
        return 2


if __name__=="__main__":
    raise SystemExit(main())
