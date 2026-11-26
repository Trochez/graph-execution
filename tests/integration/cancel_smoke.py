"""Real Temporal cancellation: stop new dispatch while a bounded worker is active."""
import asyncio
import json
from datetime import timedelta
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from graph_execution_runtime.durable_workflows import GraphRun,AgentSession
from graph_execution_runtime.scheduler import ready

started=asyncio.Event()
applies=0

@activity.defn
async def graph_ready(data:dict)->list[str]:
    return ready(data["tasks"],data["states"],data["capacity"])

@activity.defn
async def agent_turn(packet:dict)->dict:
    started.set()
    await asyncio.sleep(1.5)
    return {"disposition":"submitted","edits":[],"model_requests":1,"attempt":packet["attempt"]}

@activity.defn
async def apply_proposal(packet:dict)->dict:
    global applies
    applies+=1
    raise AssertionError("cancelled proposal must never integrate")

async def main():
    def task(k,deps):
        return {"id":k,"owner":"A","dependencies":deps,"writes":[],"reads":[],"resources":[],
            "checks":["fixture"],"timeout":20,"request_budget":3}
    spec={"workflow_id":"cancel-fixture","tasks":{"A":task("A",[]),"B":task("B",["A"])},
          "agents":{"M":{"role":"master"},"A":{"role":"worker"}},"master":"M","model":"test:fixture",
          "source_hashes":{"plan":"fixture"},"capacity":1,"run_timeout":60}
    async with await WorkflowEnvironment.start_local() as env:
        async with Worker(env.client,task_queue="cancel-fixture",workflows=[GraphRun,AgentSession],
                          activities=[graph_ready,agent_turn,apply_proposal]):
            h=await env.client.start_workflow(GraphRun.run,spec,id=spec["workflow_id"],task_queue="cancel-fixture",
                                             execution_timeout=timedelta(seconds=90))
            await asyncio.wait_for(started.wait(),15)
            await h.signal(GraphRun.stop,"fixture cancellation")
            result=await asyncio.wait_for(h.result(),30)
            assert result["cancelled"] and result["finished"]
            assert all(x["status"]=="cancelled" for x in result["tasks"].values()),result
            assert applies==0 and result["tasks"]["B"]["attempt"]==0
    print(json.dumps({"probe":"PASS","cancelled":True,"dependent_not_started":True,"integrations":applies}))

if __name__=="__main__":
    asyncio.run(main())
