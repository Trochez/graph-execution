"""Real Temporal test server + actual Pydantic Agent tool calls (no provider)."""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from pydantic_ai import ModelResponse, TextPart, ToolCallPart, models
from pydantic_ai.models.function import FunctionModel
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker, Replayer

from graph_execution_runtime.activities import Activities
from graph_execution_runtime.durable_workflows import GraphRun, AgentSession

models.ALLOW_MODEL_REQUESTS = False


def model_for(task):
    def respond(messages, info):
        returns={}
        for msg in messages:
            for p in msg.parts:
                if p.part_kind == "tool-return":
                    returns[p.tool_name]=p.content
        key=task["id"]
        if key=="a":
            if "send_message" not in returns:
                return ModelResponse(parts=[ToolCallPart("send_message",{"recipient":"b","text":"contract-v1","message_key":"contract"})])
            assert json.loads(returns["send_message"])["accepted"]
            content="contract-v1"
        elif key=="b":
            if "wait_messages" not in returns:
                return ModelResponse(parts=[ToolCallPart("wait_messages",{})])
            msg=json.loads(returns["wait_messages"])[0]
            if "acknowledge_message" not in returns:
                return ModelResponse(parts=[ToolCallPart("acknowledge_message",{"message_id":msg["id"]})])
            assert returns["acknowledge_message"] is True
            content=msg["text"]
        elif key=="join":
            if "read_file" not in returns:
                return ModelResponse(parts=[ToolCallPart("read_file",{"path":"a.txt"})])
            content=returns["read_file"]+"-joined"
        else:
            if "read_file" not in returns:
                return ModelResponse(parts=[ToolCallPart("read_file",{"path":"join.txt"})])
            assert returns["read_file"]=="contract-v1-joined"
            return ModelResponse(parts=[TextPart("reviewed")])
        if "propose_file" not in returns:
            return ModelResponse(parts=[ToolCallPart("propose_file",{"path":task["writes"][0],"content":content})])
        assert str(returns["propose_file"]).startswith("PROPOSED")
        return ModelResponse(parts=[TextPart("proposal submitted")])
    return FunctionModel(respond)


def task(key,owner,deps=(),writes=(),reads=()):
    return {"id":key,"owner":owner,"dependencies":list(deps),"writes":list(writes),"reads":list(reads),"resources":[],
            "source":"synthetic plan","outcome":"synthetic task "+key,"checks":["actual expected file content"],
            "timeout":45,"request_budget":6,"priority":0}


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)/"work";root.mkdir()
        tasks={"a":task("a","a",writes=["a.txt"]),"b":task("b","b",writes=["b.txt"]),
               "join":task("join","a",["a","b"],["join.txt"],["a.txt","b.txt"]),
               "review":task("review","r",["join"],[],["join.txt"])}
        spec={"workflow_id":"integration-smoke","tasks":tasks,"agents":{"m":{"role":"master"},"a":{"role":"worker"},"b":{"role":"worker"},"r":{"role":"reviewer"}},
              "master":"m","capacity":2,"run_timeout":120,"model":"test:synthetic","source_hashes":{"plan":"synthetic"}}
        async with await WorkflowEnvironment.start_local() as env:
            acts=Activities(env.client,root,Path(tmp)/"journal",spec["model"],model_for,approved_spec=spec)
            def worker():
                return Worker(env.client,task_queue="gexec-smoke",workflows=[GraphRun,AgentSession],
                              activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready])
            async with worker():
                handle=await env.client.start_workflow(GraphRun.run,spec,id=spec["workflow_id"],task_queue="gexec-smoke",
                                                     execution_timeout=timedelta(minutes=3))
                async with asyncio.timeout(60):
                    while True:
                        s=await handle.query(GraphRun.snapshot)
                        if all(s["tasks"][k]["status"]=="verifying" for k in ("a","b")):
                            break
                        assert not any(s["tasks"][k]["status"]=="blocked" for k in ("a","b")),s
                        await asyncio.sleep(.2)
                assert not list(root.iterdir()),"worker wrote before approval"
                assert s["tasks"]["join"]["status"]=="pending"
            # Restart between submitted proposals and integration.
            async with worker():
                async with asyncio.timeout(80):
                    while True:
                        s=await handle.query(GraphRun.snapshot)
                        if s["finished"]:break
                        for key,state in s["tasks"].items():
                            if state["status"]=="verifying":
                                p=await handle.query(GraphRun.proposal,key)
                                assert p["disposition"]=="submitted"
                                r=await handle.execute_update(GraphRun.review,{"task":key,"attempt":state["attempt"],"action":"apply","evidence":"scope reviewed"})
                                assert r["accepted"]
                            elif state["status"]=="applied":
                                if key in ("a","b"):
                                    assert (root/(key+".txt")).read_text()=="contract-v1"
                                if key in ("join","review"):
                                    assert (root/"join.txt").read_text()=="contract-v1-joined"
                                r=await handle.execute_update(GraphRun.verify,{"task":key,"attempt":state["attempt"],"passed":True,"evidence":"independent fixture file assertion"})
                                assert r["accepted"]
                            elif state["status"] in ("blocked","reconciliation_required"):
                                raise AssertionError(s)
                        await asyncio.sleep(.2)
                result=await handle.result()
            assert all(x["status"]=="done" for x in result["tasks"].values()),result
            assert any(m["status"]=="PROCESSED" for m in result["messages"])
            await Replayer(workflows=[GraphRun,AgentSession]).replay_workflow(await handle.fetch_history())
            print(json.dumps({"probe":"PASS","tasks":len(tasks),"independent_review":True,"peer_ack":True,
                              "worker_replacement":True,"replay":True,"live_model_calls":0}))

if __name__=="__main__":
    asyncio.run(main())
