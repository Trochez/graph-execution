"""Temporal-authoritative candidate runtime; only plain JSON enters workflow history."""
from __future__ import annotations

from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

from .scheduler import initialize, ready, validate_tasks
from .live_mailbox import valid_packet,generation,can_recover

NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn
class AgentSession:
    @workflow.run
    async def run(self, packet: dict) -> dict:
        return await workflow.execute_activity(
            "agent_turn", packet, result_type=dict,
            start_to_close_timeout=timedelta(seconds=packet["task"]["timeout"]),
            retry_policy=NO_RETRY,
        )


@workflow.defn
class GraphRun:
    def __init__(self):
        self.spec = {}
        self.states = {}
        self.messages = {}
        self.events = []
        self.revision = 0
        self.cancelled = False
        self.active = {}
        self.finished = False

    def event(self, kind, task=None, detail=None):
        self.revision += 1
        self.events.append({"sequence": self.revision, "kind": kind, "task": task,
                            "detail": detail, "timestamp": workflow.now().isoformat()})

    def transition(self, key, status, reason=None):
        self.states[key]["status"] = status
        self.states[key]["reason"] = reason
        self.event(status, key, reason)

    @workflow.query
    def snapshot(self) -> dict:
        tasks = {key: {**state, "result": ({k:v for k,v in state["result"].items() if k != "edits"} | {"edit_paths":[e["path"] for e in state["result"].get("edits",[])]}) if state["result"] is not None else None} for key,state in self.states.items()}
        return {"schema_version": 1, "workflow_id": workflow.info().workflow_id,
                "tasks": tasks, "messages": [{"id": m["packet"]["id"], "sender":m["packet"]["sender"], "recipient":m["packet"]["recipient"], "status":m["status"]} for m in self.messages.values()],
                "events": self.events, "revision": self.revision,
                "cancelled": self.cancelled, "finished": self.finished,
                "source_hashes": self.spec.get("source_hashes", {}),
                "model": self.spec.get("model"), "spec_sha256":self.spec.get("spec_sha256")}

    @workflow.query
    def proposal(self, task: str) -> dict | None:
        return self.states[task]["result"]

    @workflow.query
    def master_inbox(self) -> list[dict]:
        return [m["packet"] for m in self.messages.values() if m["packet"]["recipient"] == self.spec["master"] and m["status"] == "ACCEPTED"][:20]

    def check_actor(self, packet):
        key = packet.get("task")
        state = self.states.get(key)
        return (state is not None and state["status"] == "in_progress"
                and state["attempt"] == packet.get("attempt")
                and self.spec["tasks"][key]["owner"] == packet.get("sender"))

    @workflow.update
    def send(self, packet: dict) -> dict:
        v2=self.spec.get("runtime_version")==2
        if v2 and not valid_packet(packet):return {"accepted":False,"reason":"invalid typed message"}
        if v2:self.expire()
        # Only trusted activity closures may call this internal endpoint.
        # A local dev namespace is not a network authorization boundary.
        if self.cancelled or not (self.check_actor(packet) or (packet.get("sender") == self.spec["master"] and packet.get("task") is None)):
            return {"accepted": False, "reason": "inactive sender"}
        mid = packet.get("id")
        if not isinstance(mid, str) or not mid or len(mid) > 120:
            return {"accepted": False, "reason": "invalid id"}
        if mid in self.messages:
            old = self.messages[mid]
            return {"accepted": old["packet"] == packet, "duplicate": True}
        if len(self.messages) >= (513 if v2 and packet.get("kind")=="CANCEL" else 512) or packet.get("recipient") not in self.spec["agents"]:
            return {"accepted": False, "reason": "capacity or unknown recipient"}
        content = packet.get("text")
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 4096:
            return {"accepted": False, "reason": "message size"}
        if sum(m["packet"]["recipient"] == packet["recipient"] and m["status"] == "ACCEPTED"
               for m in self.messages.values()) >= 64:
            return {"accepted": False, "reason": "recipient capacity"}
        kind = packet.get("kind", "HANDOFF")
        if kind not in (("QUESTION","ANSWER","HANDOFF","PROGRESS","BLOCKED","CANCEL") if v2 else ("QUESTION","ANSWER","HANDOFF","PROGRESS","BLOCKED")):
            return {"accepted": False, "reason": "unsupported agent message kind"}
        if kind=="CANCEL" and packet["sender"]!=self.spec["master"]:return {"accepted":False,"reason":"master-only control"}
        if kind == "ANSWER":
            original = self.messages.get(packet.get("correlation_id"))
            if not original or original["packet"].get("kind") != "QUESTION" or original["packet"]["sender"] != packet["recipient"] or original["packet"]["recipient"] != packet["sender"] or original["status"] in ("EXPIRED", "DEAD_LETTERED"):
                return {"accepted": False, "reason": "invalid correlation"}
            if v2 and original.get("recipient_generation") not in (None,generation(packet)):
                return {"accepted":False,"reason":"stale response generation"}
        sequence = 1 + sum(m["packet"]["sender"] == packet["sender"] and m["packet"]["recipient"] == packet["recipient"] for m in self.messages.values())
        self.messages[mid] = {"packet": packet, "sequence": sequence, "status": "ACCEPTED",
                              "expires_at": (workflow.now() + timedelta(seconds=120)).isoformat()}
        if v2:
            self.messages[mid].update(protocol_version=2,sender_generation=generation(packet),recipient_generation=None)
        self.event("message_accepted", packet["task"], mid)
        if v2 and kind=="CANCEL":self.stop("master control message")
        return {"accepted": True, "duplicate": False}

    def expire(self):
        from datetime import datetime
        for mid, msg in self.messages.items():
            if msg["status"] == "ACCEPTED" and datetime.fromisoformat(msg["expires_at"]) <= workflow.now():
                msg["status"] = "EXPIRED"
                self.event("message_expired", detail=mid)

    @workflow.update
    def inbox(self, packet: dict) -> list[dict]:
        if self.cancelled or not self.check_actor(packet):
            return []
        self.expire()
        if self.spec.get("runtime_version")==2:
            g=generation(packet)
            eligible=[m for m in self.messages.values() if m["status"]=="ACCEPTED" and m["packet"]["recipient"]==packet["sender"] and m.get("recipient_generation") in (None,g)]
            eligible.sort(key=lambda m:m["packet"]["kind"]!="CANCEL")
            for m in eligible[:20]:m["recipient_generation"]=g
            return [m["packet"] for m in eligible[:20]]
        return [m["packet"] for m in self.messages.values()
                if m["status"] == "ACCEPTED" and m["packet"]["recipient"] == packet["sender"]][:20]

    @workflow.update
    def ack(self, packet: dict) -> bool:
        if self.cancelled or not (self.check_actor(packet) or (packet.get("sender") == self.spec["master"] and packet.get("task") is None)):
            return False
        self.expire()
        m = self.messages.get(packet.get("id"))
        if not m or m["packet"]["recipient"] != packet["sender"]:
            return False
        if self.spec.get("runtime_version")==2:
            g=generation(packet)
            if m.get("recipient_generation") not in (None,g):return False
            if packet.get("task") is not None and m.get("recipient_generation") is None:return False
            m["recipient_generation"]=g
        if m["status"] == "PROCESSED":
            return True
        if m["status"] != "ACCEPTED":
            return False
        m["status"] = "PROCESSED"
        self.event("message_processed", packet["task"], packet["id"])
        return True

    @workflow.update
    def review(self, decision: dict) -> dict:
        key = decision.get("task")
        s = self.states.get(key)
        if self.cancelled or not s or s["status"] != "verifying":
            return {"accepted": False, "reason": "not verifying"}
        if decision.get("attempt") != s["attempt"]:
            return {"accepted": False, "reason": "stale attempt"}
        action = decision.get("action")
        evidence = decision.get("evidence")
        if not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 2048:
            return {"accepted": False, "reason": "missing evidence"}
        if action == "apply":
            if self.spec.get("runtime_version")==2:
                if not s["result"].get("proposal_sha256") or decision.get("proposal_sha256")!=s["result"]["proposal_sha256"]:
                    return {"accepted":False,"reason":"proposal digest mismatch"}
                s["approval"]={"attempt":s["attempt"],"proposal_sha256":decision["proposal_sha256"],"evidence":evidence}
            self.transition(key, "applying", evidence)
        elif action == "repair" and s["attempt"] < 2:
            s["used_requests"] = s.get("used_requests",0) + s["result"].get("model_requests",0)
            if s["used_requests"] >= self.spec["tasks"][key]["request_budget"]:
                self.transition(key, "blocked", "request budget exhausted")
            else:
                s["repair_reason"] = evidence
                s["result"] = None
                self.transition(key, "pending", evidence)
        elif action == "block" or action == "repair":
            self.transition(key, "blocked", evidence)
        else:
            return {"accepted": False, "reason": "unknown action"}
        return {"accepted": True}

    @workflow.update
    def verify(self, decision: dict) -> dict:
        key = decision.get("task")
        s = self.states.get(key)
        if self.cancelled or not s or s["status"] != "applied" or s["attempt"] != decision.get("attempt"):
            return {"accepted": False, "reason": "not applied or stale attempt"}
        if not isinstance(decision.get("evidence"), str) or not decision["evidence"].strip() or len(decision["evidence"]) > 2048:
            return {"accepted": False, "reason": "missing integrated check evidence"}
        if decision.get("passed") is True:
            self.transition(key, "done", decision["evidence"])
        else:
            # After effects, automatic retry could overwrite user changes.
            self.transition(key, "reconciliation_required", decision["evidence"])
        return {"accepted": True}

    @workflow.signal
    def stop(self, reason: str):
        if not self.cancelled:
            self.cancelled = True
            self.event("cancel_requested", detail=reason[:512])

    async def run_turn(self, key):
        s = self.states[key]
        s["attempt"] += 1
        self.transition(key, "assigned")
        attempt = s["attempt"]
        packet = {"parent": workflow.info().workflow_id, "task": self.spec["tasks"][key],
                  "attempt": attempt, "model": self.spec.get("agent_models",{}).get(self.spec["tasks"][key]["owner"],self.spec["model"]), "agents": list(self.spec["agents"]),
                  "source_hashes": self.spec["source_hashes"], "repair_reason": s.get("repair_reason"),
                  "remaining_requests": self.spec["tasks"][key]["request_budget"] - s.get("used_requests",0)}
        if self.spec.get("runtime_version")==2:
            # Conservatively partition per-task requests across at most two attempts.
            packet["remaining_requests"]=max(1,packet["task"]["request_budget"]//2)
        self.transition(key, "in_progress")
        try:
            child = await workflow.start_child_workflow(AgentSession.run, packet,
                id=f"{workflow.info().workflow_id}/{key}/{attempt}",
                execution_timeout=timedelta(seconds=packet["task"]["timeout"] + 30))
            result = await child
            s["result"] = result
            if self.cancelled:
                self.transition(key, "cancelled", "proposal not applied")
            elif result.get("disposition") == "submitted":
                if self.spec.get("runtime_version")==2 and (result.get("attempt")!=attempt or not result.get("container_stopped") or not result.get("proposal_sha256")):
                    self.transition(key,"blocked","invalid fenced proposal")
                else:self.transition(key, "verifying")
            elif self.spec.get("runtime_version")==2 and result.get("disposition")=="retryable" and result.get("container_stopped") and attempt==1 and can_recover(self.messages,key,attempt):
                g={"task":key,"attempt":attempt}
                for mid,m in self.messages.items():
                    if m.get("sender_generation")==g and m["status"]=="ACCEPTED":
                        m["status"]="DEAD_LETTERED";self.event("message_dead_lettered",key,mid)
                    elif m.get("recipient_generation")==g and m["status"] in ("ACCEPTED","PROCESSED"):
                        m["recipient_generation"]=None;m["status"]="ACCEPTED";self.event("message_redeliver",key,mid)
                s["repair_reason"]="previous isolated container stopped; restart with fresh scratch"
                s["result"]=None
                self.event("worker_recovery",key,{"discarded_attempt":attempt,"container_stopped":True})
                self.transition(key,"pending",s["repair_reason"])
            else:
                self.transition(key, "blocked", result.get("reason", "agent did not submit"))
        except Exception as exc:
            self.transition(key, "blocked", "agent activity failed: " + type(exc).__name__)

    async def apply_turn(self, key):
        s = self.states[key]
        try:
            result = await workflow.execute_activity("apply_proposal",
                {"parent": workflow.info().workflow_id, "task": self.spec["tasks"][key],
                 "attempt": s["attempt"], "result": s["result"], "source_hashes": self.spec["source_hashes"],
                 **({"approval":s["approval"]} if self.spec.get("runtime_version")==2 else {})},
                result_type=dict, start_to_close_timeout=timedelta(seconds=180 if self.spec.get("runtime_version")==2 else 60), retry_policy=NO_RETRY)
            s["integration"] = result
            if result.get("applied") and not self.cancelled:
                self.transition(key, "applied")
            else:
                self.transition(key, "reconciliation_required", "integration failed or cancellation")
        except Exception:
            self.transition(key, "reconciliation_required", "integration outcome unknown; inspect journal")

    @workflow.run
    async def run(self, spec: dict) -> dict:
        self.spec = spec
        validate_tasks(spec["tasks"], spec["agents"], spec["master"])
        self.states = initialize(spec["tasks"])
        self.event("started")
        import asyncio
        deadline = workflow.now() + timedelta(seconds=spec["run_timeout"])
        while True:
            self.expire()
            for key in list(self.active):
                if self.active[key].done():
                    await self.active.pop(key)
            if workflow.now() >= deadline and not self.cancelled:
                self.stop("run deadline")
            if self.cancelled:
                # Stop dispatch; drain bounded in-flight operations, never assert rollback.
                for key, state in self.states.items():
                    if key not in self.active and state["status"] not in ("done", "blocked", "reconciliation_required", "cancelled"):
                        status = "reconciliation_required" if state["status"] in ("applied", "applying") else "cancelled"
                        self.transition(key, status, "run stopped")
                if not self.active:
                    break
            else:
                # Serialize integration, while independent proposal-only workers may proceed.
                if not any(self.states[k]["status"] == "applying" for k in self.active):
                    for key, state in self.states.items():
                        if state["status"] == "applying" and key not in self.active:
                            self.active[key] = asyncio.create_task(self.apply_turn(key))
                            break
                candidates = ready(spec["tasks"], self.states, spec["capacity"])
                if candidates:
                    revision = self.revision
                    checked = await workflow.execute_activity("graph_ready", {"tasks":spec["tasks"], "states":{k:{"status":s["status"]} for k,s in self.states.items()}, "capacity":spec["capacity"]}, result_type=list[str], start_to_close_timeout=timedelta(seconds=15), retry_policy=NO_RETRY)
                    if self.revision != revision:
                        continue
                    if checked != candidates:
                        raise ApplicationError("graph decision differs from deterministic scheduler", non_retryable=True)
                for key in candidates:
                    if key not in self.active:
                        self.transition(key, "ready")
                        self.active[key] = asyncio.create_task(self.run_turn(key))
                if not self.active and not any(s["status"] in ("verifying", "applying", "applied", "ready", "in_progress", "assigned") for s in self.states.values()):
                    if not ready(spec["tasks"], self.states, spec["capacity"]):
                        for key, state in self.states.items():
                            if state["status"] == "pending":
                                self.transition(key, "blocked", "unverified prerequisites or reserved resources")
                        break
            rev = self.revision
            try:
                await workflow.wait_condition(lambda: self.revision != rev or any(t.done() for t in self.active.values()),
                                              timeout=timedelta(seconds=2))
            except asyncio.TimeoutError:
                pass
        for mid, msg in self.messages.items():
            if msg["status"] == "ACCEPTED":
                msg["status"] = "DEAD_LETTERED"
                self.event("message_dead_lettered", detail=mid)
        self.finished = True
        self.event("finished")
        return self.snapshot()
