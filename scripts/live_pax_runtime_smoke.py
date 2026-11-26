"""Opt-in live qualification of the installed Pax master and durable worker runtime.

Runs exclusively against a new synthetic workspace and a dedicated queue in the
operator's existing local Temporal server. Makes real bounded provider requests.
Never modifies the global Pax/model policy or an existing target repository.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import secrets
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

from temporalio.client import Client
from temporalio.worker import Worker

from graph_execution_runtime.activities import Activities
from graph_execution_runtime.cli import private_json
from graph_execution_runtime.config import prepare
from graph_execution_runtime.durable_workflows import GraphRun, AgentSession
from graph_execution_runtime.operator import Controller, discover_models, model_factory, local_address


ROOT=Path(__file__).resolve().parent.parent


def fixture(out,base_url,model):
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    work=out/"workspace";work.mkdir()
    secret="contract-"+secrets.token_hex(8)
    plan=out/"plan.md";plan.write_text("# Disposable peer handoff fixture\nCreate two matching contract files via peer message, then integrate and review.\n")
    def task(k,outcome,depends=()):
        return {"id":k,"source":"plan.md#disposable-peer-handoff-fixture","outcome":outcome,
                "verification":"operator-provided deterministic file check","depends_on":list(depends),"duration":1}
    tasks=out/"tasks.json"
    private_json(tasks,{"unit":"hours","tasks":[
        task("A",f"Send a HANDOFF message to agent B with the exact contract {secret}, using send_message. Propose a.txt containing exactly that contract with no newline."),
        task("B","Use wait_messages to obtain A's contract; acknowledge its message ID and propose b.txt containing exactly the received text with no newline. Do not guess the contract."),
        task("J","Read a.txt and b.txt and propose join.txt with their identical text followed by -joined.",["A","B"]),
        task("R","Independently review join.txt and report whether it matches the integrated contracts. Do not write files.",["J"])]})
    team=out/"team.json"
    private_json(team,{"agents":[{"id":x} for x in ("M","A","B","R")],
                       "task_assignments":[{"task_id":k,"owner_agent_id":a} for k,a in (("A","A"),("B","B"),("J","A"),("R","R"))]})
    def check(name,text):
        return [sys.executable,"-c",f"from pathlib import Path; assert Path({name!r}).read_text()=={text!r}"]
    settings={"roles":{"M":"master","A":"worker","B":"worker","R":"reviewer"},
              "parents":{"M":None,"A":"M","B":"M","R":"M"},"master":"M","model":model,"capacity":2,"run_timeout":600,
              "scopes":{"A":{"reads":[],"writes":["a.txt"],"timeout":120,"request_budget":10},
                        "B":{"reads":[],"writes":["b.txt"],"timeout":120,"request_budget":10},
                        "J":{"reads":["a.txt","b.txt"],"writes":["join.txt"],"timeout":120,"request_budget":8},
                        "R":{"reads":["join.txt","a.txt","b.txt"],"writes":[],"timeout":120,"request_budget":6}}}
    spec=prepare("gexec-live-smoke-"+uuid4().hex,plan,tasks,team,settings)
    approval=out/"approval.json";private_json(approval,{"model":model,"base_url":base_url,"month":date.today().strftime("%Y-%m"),"confirmation":model})
    bundle=out/"bundle.json";private_json(bundle,{"spec":spec,"workspace":str(work),"skill_root":str(ROOT),"journal":str(out/"journal"),
        "base_url":base_url,"approval":str(approval),"sources":{"plan":str(plan),"tasks":str(tasks),"team":str(team)},
        "check_commands":{"A":[check("a.txt",secret)],"B":[check("b.txt",secret)],"J":[check("join.txt",secret+"-joined")],"R":[check("join.txt",secret+"-joined")]},
        "final_checks":[check("a.txt",secret),check("b.txt",secret),check("join.txt",secret+"-joined")]})
    return bundle,spec,work


async def run(args,key):
    if args.model != args.confirm_model or not args.model.startswith("openai:"):
        raise ValueError("explicit matching provider-qualified model confirmation required")
    if args.model[7:] not in await discover_models(args.base_url,key):
        raise ValueError("route absent from advertised inventory")
    bundle,spec,work=fixture(args.output.resolve(),args.base_url,args.model)
    client=await Client.connect(local_address(args.address))
    acts=Activities(client,work,bundle.parent/"journal",args.model,
                    lambda task:model_factory(args.base_url,key,args.model),ROOT,approved_spec=spec,bundle_path=bundle)
    c=Controller(client,bundle)
    pax=Path(sys.executable).parent/("pax.exe" if os.name=="nt" else "pax")
    if not pax.is_file():
        raise ValueError("install Pax in the same isolated runtime environment")
    env=dict(os.environ,GEXEC_RUN_BUNDLE=str(bundle),GEXEC_PROBE_API_KEY=key,GEXEC_TEMPORAL_ADDRESS=args.address,
             PYTHON_DOTENV_DISABLED="1",PYDANTIC_AI_NO_BANNER="1")
    env.pop("GEXEC_PIPELINE_CONFIG",None)
    prompt=("Use the actual native-plan-executor skill in the current configured Pax bridge. "
            "Start the approved graph, inspect status and each proposal; review and apply valid proposals, "
            "then verify every integrated task using the provided runtime tools. Use gexec_wait with the "
            "latest revision rather than tight polling. Do not tell B the contract; B must receive A's "
            "peer message. Finalize only after all four tasks are verified; call gexec_finalize. "
            "This is an authorized disposable fixture; no unrelated actions. If blocked, report the exact stage.")
    async with Worker(client,task_queue=spec["workflow_id"],workflows=[GraphRun,AgentSession],
                      activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready]):
        proc=await asyncio.create_subprocess_exec(str(pax),"--agent","graph_execution_runtime.pax_bridge:agent",
            "--database",str(bundle.parent/"pax.db"),"--request-limit","60","-p",prompt,
            cwd=work,env=env,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
        try:
            output,_=await asyncio.wait_for(proc.communicate(),timeout=660)
        except asyncio.TimeoutError:
            proc.kill();await proc.wait()
            try:await c.stop("live smoke master timeout")
            except Exception:pass
            raise
        # Keep raw model transcript local; only summarize actual workflow facts.
        log=bundle.parent/"pax-local.log"
        fd=os.open(log,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,"wb") as f:f.write(output)
        s=await c.status()
        receipt_path=bundle.parent/"journal/records/final-checks.json"
        final=json.loads(receipt_path.read_text()) if receipt_path.is_file() else {"passed":False}
        peer=any(m["sender"]=="A" and m["recipient"]=="B" and m["status"]=="PROCESSED" for m in s["messages"])
        passed=proc.returncode==0 and s["finished"] and not s["cancelled"] and all(t["status"]=="done" for t in s["tasks"].values()) and final["passed"] and peer
        if not s["finished"]:
            await c.stop("live smoke ended without finalization")
        report={"probe":"PASS" if passed else "FAIL","workflow_id":spec["workflow_id"],"pax_exit":proc.returncode,
                "tasks":{k:v["status"] for k,v in s["tasks"].items()},"peer_ack":peer,
                "final_checks":final["passed"],"requested_model":args.model,"effective_model":"unknown",
                "master":"actual Pax custom-agent CLI","live_model_calls":True,
                "scope":"disposable executor fixture; not full release qualification"}
        private_json(bundle.parent/"receipt.json",report)
        return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url",required=True);p.add_argument("--model",required=True)
    p.add_argument("--confirm-model",required=True);p.add_argument("--output",required=True,type=Path)
    p.add_argument("--address",default="localhost:7233")
    args=p.parse_args()
    key=os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
    try:
        result=asyncio.run(run(args,key));print(json.dumps(result,indent=2));return 0 if result["probe"]=="PASS" else 2
    except Exception as exc:
        print(json.dumps({"probe":"FAIL","error_type":type(exc).__name__,"note":"inspect local fixture records; do not share secrets"}))
        return 2

if __name__=="__main__":
    raise SystemExit(main())
