"""Deterministic workflow only: no SDK/model, filesystem, or provider imports."""
from __future__ import annotations

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError


@workflow.defn
class PeerMailbox:
    def __init__(self):
        self.contract = None
        self.acked = False
        self.phase = "publisher"

    @workflow.update
    def publish(self, value: str) -> bool:
        if self.phase != "publisher" or self.contract is not None:
            return False
        if not value.startswith("contract-") or len(value) != 33:
            return False
        self.contract = value
        return True

    @workflow.query
    def receive(self) -> str | None:
        return self.contract if self.phase == "consumer" else None

    @workflow.update
    def acknowledge(self, value: str) -> bool:
        if self.phase != "consumer" or not self.contract or value != self.contract:
            return False
        if self.acked:
            return False
        self.acked = True
        return True

    @workflow.run
    async def run(self, nonce: str) -> dict:
        common = {
            "start_to_close_timeout": timedelta(seconds=90),
            "retry_policy": RetryPolicy(maximum_attempts=1),
        }
        a = await workflow.execute_activity("peer_turn", {"role": "publisher", "nonce": nonce},
                                            result_type=dict, **common)
        if not a["tool_called"] or self.contract != nonce:
            raise ApplicationError("publisher did not publish")
        self.phase = "consumer"
        # Consumer assignment intentionally contains no nonce or publisher transcript.
        b = await workflow.execute_activity("peer_turn", {"role": "consumer"},
                                            result_type=dict, **common)
        if not b["tool_called"] or not self.acked or b["output"] != nonce:
            raise ApplicationError("consumer did not return the received contract")
        self.phase = "done"
        return {"publisher": a["role"], "consumer": b["role"], "peer_ack": True,
                "consumer_verified": True, "agent_turns": 2,
                "model_requests": a["requests"] + b["requests"]}

