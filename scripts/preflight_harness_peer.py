"""Bounded feasibility test: independent Harness contexts and Temporal peer exchange.

Default uses TestModel (no provider calls). Live mode explicitly opts into one model
and has no shell tools, file mutation tools, fallback routes, or automatic retries.
This is not the production runtime. A completed turn is the checkpoint boundary.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import secrets
import tempfile
from datetime import timedelta
from urllib.parse import urlsplit
import traceback
from importlib.metadata import version
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import UsageLimits
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import Skills
from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, Worker

from preflight_peer_workflow import PeerMailbox

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = {"gexec", "critical-path-planner", "backlog-team-designer", "native-plan-executor"}


def skills():
    return Skills("skills", workspace=LocalWorkspaceBackend(ROOT), include=sorted(EXPECTED))


async def discover():
    catalog = await skills().load()
    names = sorted(s.name for s in catalog.skills)
    if set(names) != EXPECTED or catalog.skipped:
        raise RuntimeError("skill discovery mismatch")
    return names




class PeerActivities:
    def __init__(self, client: Client, model, nonce: str):
        self.client = client
        self.model = model
        self.nonce = nonce
        self.attempts = 0

    @activity.defn
    async def peer_turn(self, packet: dict) -> dict:
        self.attempts += 1
        role = packet["role"]
        if role not in ("publisher", "consumer"):
            raise ValueError("unknown role")
        handle = self.client.get_workflow_handle(activity.info().workflow_id)
        tool_called = False

        # Every turn gets a separate agent, no shared transcript and no Coder
        # shell/file tools. Skills is a real Harness capability, read-only here.
        model = self.model
        if model is None:
            model = TestModel(call_tools=["publish_contract" if role == "publisher" else
                                          "receive_contract"],
                              custom_output_text="PUBLISHED" if role == "publisher" else self.nonce)
        agent = Agent(model, capabilities=[skills()],
                      instructions="This is a synthetic protocol test. Use only the assigned "
                                   "mailbox tool; never load or execute implementation instructions.")
        if role == "publisher":
            @agent.tool_plain
            async def publish_contract() -> str:
                """Publish this assignment's synthetic contract to the consumer."""
                nonlocal tool_called
                accepted = await handle.execute_update(PeerMailbox.publish, packet["nonce"])
                if not accepted:
                    raise RuntimeError("publish rejected")
                tool_called = True
                return "published"
            prompt = "Call publish_contract exactly once. Then reply PUBLISHED."
        else:
            @agent.tool_plain
            async def receive_contract() -> str:
                """Read the publisher's contract and acknowledge its exact value."""
                nonlocal tool_called
                value = await handle.query(PeerMailbox.receive)
                if value is None:
                    raise RuntimeError("no peer contract")
                accepted = await handle.execute_update(PeerMailbox.acknowledge, value)
                if not accepted:
                    raise RuntimeError("acknowledgement rejected")
                tool_called = True
                return value
            prompt = "Call receive_contract exactly once. Reply with its exact returned value, nothing else."
        async with asyncio.timeout(75):
            result = await agent.run(prompt, usage_limits=UsageLimits(request_limit=4, tool_calls_limit=3))
        usage = result.usage
        if callable(usage):
            usage = usage()
        return {"role": role, "tool_called": tool_called, "output": str(result.output).strip(),
                "requests": usage.requests}


def validate_live_config(model_id: str, base_url: str | None):
    if ":" not in model_id or model_id.startswith(("chain:", "test:", "demo:")) or not model_id.split(":", 1)[1].strip() or "YOUR_" in model_id.upper():
        raise ValueError("Supply an actual provider-qualified model ID, not a placeholder.")
    if base_url:
        url = urlsplit(base_url)
        if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment or "YOUR_" in base_url.upper():
            raise ValueError("Supply the actual HTTP(S) OpenAI-compatible base URL, without credentials or placeholders.")
        if not model_id.startswith("openai:"):
            raise ValueError("A custom base URL requires an openai: model ID.")


def build_live_model(model_id: str, base_url: str | None, api_key: str | None):
    validate_live_config(model_id, base_url)
    if base_url:
        if not model_id.startswith("openai:"):
            raise ValueError("for OpenAI-compatible base URL use openai:EXACT_MODEL_ID")
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=45)
        return OpenAIChatModel(model_id.split(":", 1)[1],
                               provider=OpenAIProvider(openai_client=client))
    return model_id


async def execute_probe(model=None, requested_model: str | None = None) -> dict:
    names = await discover()
    nonce = "contract-" + secrets.token_hex(12)
    workflow_id = "gexec-peer-spike-" + secrets.token_hex(8)
    async with await WorkflowEnvironment.start_local() as env:
        peer = PeerActivities(env.client, model, nonce)
        async with Worker(env.client, task_queue=workflow_id, workflows=[PeerMailbox],
                          activities=[peer.peer_turn]):
            handle = await env.client.start_workflow(
                PeerMailbox.run, nonce, id=workflow_id, task_queue=workflow_id,
                execution_timeout=timedelta(minutes=4),
            )
            result = await asyncio.wait_for(handle.result(), timeout=210)
        await Replayer(workflows=[PeerMailbox]).replay_workflow(await handle.fetch_history())
        if peer.attempts != 2:
            raise RuntimeError("unexpected repeat execution")
    return {"probe": "PASS", "model_mode": "live" if model is not None else "TestModel",
            "requested_model": requested_model, "effective_provider_route": "unverified",
            "skills": names, "replay": True, "activity_attempts": peer.attempts,
            "checkpoint_boundary": "whole-turn activity", "pax_master": "not tested by this function",
            "full_host_qualification": False, "result": result,
            "versions": {p: version(p) for p in ("pydantic-ai-pax", "pydantic-ai-harness",
                                                   "pydantic-ai-slim", "temporalio")}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live-model", help="Explicit opt-in to model requests; provider-qualified exact model ID")
    p.add_argument("--base-url", help="Optional OpenAI-compatible URL, e.g. your own OmniRoute API endpoint")
    args = p.parse_args()
    if args.base_url and not args.live_model:
        p.error("--base-url requires --live-model")
    if args.live_model:
        try:
            validate_live_config(args.live_model, args.base_url)
        except ValueError as exc:
            p.error(str(exc))
    try:
        key = (os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
               if args.base_url else None)
        model = build_live_model(args.live_model, args.base_url, key) if args.live_model else None
        result = asyncio.run(execute_probe(model, args.live_model))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # For live runs report only exception classes and code locations; never provider payloads.
        if not args.live_model:
            traceback.print_exc()
        chain = []
        current = exc
        seen = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            frames = traceback.extract_tb(current.__traceback__)
            chain.append({"type": type(current).__name__, "frames": [
                {"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                for frame in frames[-5:]]})
            current = current.__cause__ or current.__context__
        print(json.dumps({"probe": "FAIL", "error_type": type(exc).__name__, "diagnostics": chain}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
