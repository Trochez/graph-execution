"""Candidate pure mailbox protocol. Persistence/authentication belong to the future host bridge.

The caller must provide authenticated principals and authoritative time; this class
does not itself authenticate a process or persist state. It is suitable for testing
deterministic transitions, not production delivery.
"""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from .contracts import Contract, Id, Positive, Text


class Question(Contract):
    kind: Literal["QUESTION"] = "QUESTION"
    text: Text


class Answer(Contract):
    kind: Literal["ANSWER"] = "ANSWER"
    text: Text


class Progress(Contract):
    kind: Literal["PROGRESS"] = "PROGRESS"
    text: Text


class Cancel(Contract):
    kind: Literal["CANCEL"] = "CANCEL"
    reason: Text


Payload = Annotated[Question | Answer | Progress | Cancel, Field(discriminator="kind")]


class Principal(Contract):
    agent_id: Id
    generation: Positive


class MessageDraft(Contract):
    message_id: UUID
    recipient_id: Id
    recipient_generation: Positive | None = None
    conversation_id: Id
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    task_id: Id | None = None
    attempt_id: Id | None = None
    deadline: AwareDatetime
    payload: Payload

    @model_validator(mode="after")
    def correlation(self):
        if self.payload.kind == "ANSWER" and self.correlation_id is None:
            raise ValueError("ANSWER requires correlation_id")
        if (self.task_id is None) != (self.attempt_id is None):
            raise ValueError("task/attempt must be provided together")
        return self


class Envelope(Contract):
    protocol_version: Literal["1.0"] = "1.0"
    run_id: Id
    run_epoch: Positive
    sender: Principal
    sequence: Positive
    lane: Literal["data", "control"]
    created_at: AwareDatetime
    draft: MessageDraft


class Receipt(Contract):
    message_id: UUID
    status: Literal["ACCEPTED", "PROCESSED", "REJECTED", "EXPIRED", "DEAD_LETTERED"]
    sequence: Positive
    reason: Text | None = None


def digest(principal: Principal, draft: MessageDraft) -> str:
    data = [principal.model_dump(mode="json"), draft.model_dump(mode="json")]
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Mailbox:
    """Single-authority in-memory state; to be embedded in a durable workflow later."""

    def __init__(self, run_id: str, epoch: int, master: str, members: dict[str, int],
                 max_messages: int = 1000):
        if master not in members or max_messages < 1 or epoch < 1 or any(n < 1 for n in members.values()):
            raise ValueError("invalid mailbox configuration")
        self.run_id, self.epoch, self.master = run_id, epoch, master
        self.members = dict(members)
        self.max_messages = max_messages
        self.closed = set()
        self.entries: dict[UUID, Envelope] = {}
        self.receipts: dict[UUID, Receipt] = {}
        self.hashes: dict[UUID, str] = {}
        self.sequences: dict[tuple, int] = {}

    def _check(self, principal: Principal):
        if principal.agent_id in self.closed or self.members.get(principal.agent_id) != principal.generation:
            raise PermissionError("stale, closed or unknown principal")

    def send(self, principal: Principal, draft: MessageDraft, now) -> Receipt:
        self._check(principal)
        key = draft.message_id
        checksum = digest(principal, draft)
        if key in self.hashes:
            if self.hashes[key] != checksum:
                raise ValueError("message ID collision")
            return self.receipts[key]
        if draft.recipient_id not in self.members or draft.recipient_id in self.closed:
            raise ValueError("unknown or closed recipient")
        if draft.recipient_generation not in (None, self.members[draft.recipient_id]):
            raise ValueError("stale recipient generation")
        if draft.deadline <= now:
            raise ValueError("message already expired")
        if draft.payload.kind == "CANCEL" and principal.agent_id != self.master:
            raise PermissionError("cancel requires master")
        if draft.payload.kind == "ANSWER":
            original = self.entries.get(draft.correlation_id)
            if (original is None or original.draft.payload.kind != "QUESTION"
                    or original.sender.agent_id != draft.recipient_id
                    or original.sender.generation != self.members[draft.recipient_id]
                    or original.draft.recipient_id != principal.agent_id
                    or original.draft.recipient_generation not in (None, principal.generation)
                    or original.draft.conversation_id != draft.conversation_id
                    or original.draft.deadline <= now):
                raise ValueError("invalid reply correlation")
        lane = "control" if draft.payload.kind == "CANCEL" else "data"
        # Reserve a finite control allowance; never silently evict dedup history.
        capacity = self.max_messages + (100 if lane == "control" else 0)
        if len(self.entries) >= capacity:
            raise OverflowError("history capacity reached; stop admission")
        scope = (draft.conversation_id, principal.agent_id, draft.recipient_id, lane)
        sequence = self.sequences.get(scope, 0) + 1
        envelope = Envelope(run_id=self.run_id, run_epoch=self.epoch, sender=principal,
                            sequence=sequence, lane=lane, created_at=now, draft=draft)
        receipt = Receipt(message_id=key, status="ACCEPTED", sequence=sequence)
        self.entries[key] = envelope
        self.receipts[key] = receipt
        self.hashes[key] = checksum
        self.sequences[scope] = sequence
        return receipt

    def expire(self, now):
        for key, envelope in self.entries.items():
            if self.receipts[key].status == "ACCEPTED" and envelope.draft.deadline <= now:
                self.receipts[key] = Receipt(message_id=key, sequence=envelope.sequence,
                                             status="EXPIRED", reason="deadline")

    def page(self, principal: Principal, now, limit: int = 20) -> list[Envelope]:
        self._check(principal)
        if not 1 <= limit <= 100:
            raise ValueError("invalid batch limit")
        self.expire(now)
        eligible = [e for key, e in self.entries.items()
                    if self.receipts[key].status == "ACCEPTED"
                    and e.draft.recipient_id == principal.agent_id
                    and e.draft.recipient_generation in (None, principal.generation)]
        return sorted(eligible, key=lambda e: e.lane != "control")[:limit]

    def acknowledge(self, principal: Principal, message_id: UUID, now, *, processed: bool) -> Receipt:
        self._check(principal)
        envelope = self.entries[message_id]
        if (envelope.draft.recipient_id != principal.agent_id
                or envelope.draft.recipient_generation not in (None, principal.generation)):
            raise PermissionError("acknowledgement from wrong recipient")
        self.expire(now)
        old = self.receipts[message_id]
        status = "PROCESSED" if processed else "REJECTED"
        if old.status != "ACCEPTED":
            if old.status != status:
                raise ValueError("conflicting or terminal acknowledgement")
            return old
        receipt = Receipt(message_id=message_id, sequence=old.sequence, status=status)
        self.receipts[message_id] = receipt
        return receipt
