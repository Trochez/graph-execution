"""Credential-free feasibility probe, NOT the production adapter or live-agent qualification."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from importlib.metadata import version

from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

calls = 0


@activity.defn
async def select_ready(tasks: list[dict]) -> list[str]:
    # Deliberate activity boundary: do not execute graph internals in workflow replay.
    from pydantic_graph import GraphBuilder, StepContext

    global calls
    calls += 1
    builder = GraphBuilder(input_type=list[dict], output_type=list[str])

    @builder.step
    async def ready(ctx: StepContext[None, None, list[dict]]) -> list[str]:
        completed = {task["id"] for task in ctx.inputs if task["done"]}
        return sorted(task["id"] for task in ctx.inputs
                      if not task["done"] and set(task["deps"]) <= completed)

    builder.add(builder.edge_from(builder.start_node).to(ready),
                builder.edge_from(ready).to(builder.end_node))
    return await builder.build().run(inputs=tasks)


@workflow.defn
class ProbeChild:
    def __init__(self) -> None:
        self.message: str | None = None

    @workflow.signal
    def receive(self, message: str) -> None:
        if self.message is None:
            self.message = message

    @workflow.run
    async def run(self) -> str:
        await workflow.wait_condition(lambda: self.message is not None)
        assert self.message is not None
        return self.message


@workflow.defn
class ProbeParent:
    def __init__(self) -> None:
        self.receipts: list[str] = []
        self.stage = "starting"
        self.release = False

    @workflow.update
    def accept(self, message_id: str) -> bool:
        if message_id in self.receipts:
            return False
        self.receipts.append(message_id)
        return True

    @workflow.signal
    def resume(self) -> None:
        self.release = True

    @workflow.query
    def get_stage(self) -> str:
        return self.stage

    @workflow.run
    async def run(self, tasks: list[dict]) -> dict:
        ready = await workflow.execute_activity(
            "select_ready", tasks, result_type=list[str],
            start_to_close_timeout=timedelta(seconds=20),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        child = await workflow.start_child_workflow(
            ProbeChild.run, id=workflow.info().workflow_id + "-child",
        )
        self.stage = "waiting"
        await workflow.wait_condition(lambda: self.release)
        await child.signal(ProbeChild.receive, "peer-contract-v1")
        reply = await child
        return {"ready": ready, "receipts": self.receipts, "reply": reply}


async def main() -> None:
    tasks = [{"id": "a", "deps": [], "done": True},
             {"id": "b", "deps": ["a"], "done": False},
             {"id": "c", "deps": ["b"], "done": False}]
    queue = "graph-execution-preflight"
    async with await WorkflowEnvironment.start_local() as env:
        def worker() -> Worker:
            return Worker(env.client, task_queue=queue,
                          workflows=[ProbeParent, ProbeChild], activities=[select_ready])

        async with worker():
            handle = await env.client.start_workflow(
                ProbeParent.run, tasks, id="graph-preflight", task_queue=queue,
                execution_timeout=timedelta(minutes=2),
            )
            async with asyncio.timeout(30):
                while await handle.query(ProbeParent.get_stage) != "waiting":
                    await asyncio.sleep(0.2)
            assert await handle.execute_update(ProbeParent.accept, "m1") is True
            assert await handle.execute_update(ProbeParent.accept, "m1") is False
        # No worker polling: the signal must survive until a replacement worker starts.
        await handle.signal(ProbeParent.resume)
        async with worker():
            result = await asyncio.wait_for(handle.result(), timeout=30)
        assert result == {"ready": ["b"], "receipts": ["m1"], "reply": "peer-contract-v1"}, result
        assert calls == 1, calls
        history = await handle.fetch_history()
        await Replayer(workflows=[ProbeParent, ProbeChild]).replay_workflow(history)
        assert calls == 1, "replay re-executed activity"
        child_history = await env.client.get_workflow_handle("graph-preflight-child").fetch_history()
        await Replayer(workflows=[ProbeParent, ProbeChild]).replay_workflow(child_history)
        assert calls == 1
        print(json.dumps({"probe": "PASS", "result": result, "activity_executions": calls,
                          "worker_restart": True, "parent_child_replay": True,
                          "live_model_calls": 0, "live_pax_qualification": False,
                          "versions": {p: version(p) for p in
                                       ("pydantic-graph", "temporalio", "pydantic-ai-pax", "pydantic-ai-harness")}},
                         sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
