"""Exercise actual Controller verification and projection, not a model claim."""
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from graph_execution_runtime.config import prepare
from graph_execution_runtime.operator import Controller,load_bundle,compact_status
from graph_execution_runtime.activities import Activities
from graph_execution_runtime.durable_workflows import GraphRun,AgentSession
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from pydantic_ai import ModelResponse,TextPart,ToolCallPart,models
from pydantic_ai.models.function import FunctionModel

models.ALLOW_MODEL_REQUESTS=False

def make_model(task):
    def respond(messages,info):
        if any(p.part_kind=="tool-return" and p.tool_name=="propose_file" for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart("submitted")])
        return ModelResponse(parts=[ToolCallPart("propose_file",{"path":"a.txt","content":"validated"})])
    return FunctionModel(respond)

async def main():
    with tempfile.TemporaryDirectory() as d:
        d=Path(d);root=d/"work";root.mkdir()
        plan=d/"plan.md";plan.write_text("# Write validated")
        tasks=d/"tasks.json";tasks.write_text(json.dumps({"tasks":[{"id":"T","source":"plan#write","outcome":"create a.txt","verification":"actual text check"}]}))
        team=d/"team.json";team.write_text(json.dumps({"agents":[{"id":"M"},{"id":"A"}],"task_assignments":[{"task_id":"T","owner_agent_id":"A"}]}))
        spec=prepare("controller-fixture",plan,tasks,team,{"roles":{"M":"master","A":"worker"},"parents":{"M":None,"A":"M"},"master":"M","model":"openai:fixture","scopes":{"T":{"reads":[],"writes":["a.txt"],"timeout":45}}})
        cmd=[sys.executable,"-c","from pathlib import Path; assert Path('a.txt').read_text()=='validated'"]
        b={"spec":spec,"workspace":str(root),"journal":str(d/"journal"),"sources":{"plan":str(plan),"tasks":str(tasks),"team":str(team)},"check_commands":{"T":[cmd]},"final_checks":[cmd]}
        bundle=d/"bundle.json";bundle.write_text(json.dumps(b))
        assert load_bundle(bundle)["spec"]==spec
        async with await WorkflowEnvironment.start_local() as env:
            acts=Activities(env.client,root,d/"journal",spec["model"],make_model,approved_spec=spec,bundle_path=bundle)
            async with Worker(env.client,task_queue=spec["workflow_id"],workflows=[GraphRun,AgentSession],activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready]):
                c=Controller(env.client,bundle)
                # Only live inventory approval is substituted; everything else is the real operator.
                with patch("graph_execution_runtime.operator.approved_bundle",return_value=b):
                    await c.start()
                async with asyncio.timeout(40):
                    while True:
                        s=await c.status();t=s["tasks"]["T"]
                        if t["status"]=="verifying":
                            assert (await c.proposal("T"))["edits"][0]["content"]=="validated"
                            brief=compact_status(s)
                            assert "events" not in brief and brief["tasks"]["T"]["next"]
                            stale=await c.review_and_verify("T",t["attempt"]+1,"stale fixture")
                            assert not stale["accepted"] and not (root/"a.txt").exists()
                            r=await c.review_and_verify("T",t["attempt"],"reviewed fixture")
                            assert r["accepted"] and r["status"]=="done",r
                            assert r["verification"]["checks"][0]["exit_code"]==0
                            repeat=await c.review_and_verify("T",t["attempt"],"same approval")
                            assert repeat["already_verified"]
                        elif t["status"]=="applied":
                            r=await c.verify("T");assert r["checks"][0]["exit_code"]==0
                        elif s["finished"]:break
                        elif t["status"] in ("blocked","reconciliation_required"):raise AssertionError(s)
                        await asyncio.sleep(.2)
                r=await c.finalize();assert r["passed"]
                assert (d/"journal/records/execution.json").is_file()
                assert (d/"journal/records/final-checks.json").is_file()
        plan.write_text("changed")
        try:load_bundle(bundle)
        except ValueError:pass
        else:raise AssertionError("stale source accepted")
    print(json.dumps({"probe":"PASS","controller":True,"actual_check":True,"records":True,"stale_source":True,"compact_master":True,"stale_attempt_rejected":True,"combined_review_verify":True}))

if __name__=="__main__":
    asyncio.run(main())
