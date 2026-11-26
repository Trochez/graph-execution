"""Versioned, host-independent candidate contracts. No vendor runtime imports."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(min_length=1, max_length=200, strip_whitespace=False)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=16384)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
Positive = Annotated[int, Field(ge=1)]
HostMode = Literal["codex-native", "cline-team", "cline-subagent", "pax-durable", "future"]
Support = Literal["supported", "unsupported", "unverified"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class RunIdentity(Contract):
    schema_version: Literal["1.0"] = "1.0"
    repository: Id
    run_id: Id
    workflow_id: Id
    epoch: Positive
    mode: HostMode
    source_commit: Revision
    source_hashes: dict[Id, Hash] = Field(min_length=1)


class ArtifactRef(Contract):
    artifact_id: Id
    path: Id
    sha256: Hash
    bytes: Annotated[int, Field(ge=0)]
    media_type: Id
    task_id: Id
    attempt_id: Id
    base_revision: Revision
    retention: Literal["run", "release", "audit"]

    @model_validator(mode="after")
    def relative_path(self):
        p = PurePosixPath(self.path)
        if (p.is_absolute() or "\\" in self.path or ":" in self.path
                or any(x in ("", ".", "..") for x in self.path.split("/"))):
            raise ValueError("artifact path must be normalized and relative")
        return self


class CapabilityReceipt(Contract):
    schema_version: Literal["1.0"] = "1.0"
    mode: HostMode
    host_version: Id
    adapter_version: Id
    evidence: list[Text] = Field(min_length=1)
    capabilities: dict[Id, Support]
    limits: dict[Id, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    inventory_coverage: Literal["complete", "partial", "unverified"]
    model_override: Support
    limitations: list[Text] = Field(default_factory=list)


class ApprovalReceipt(Contract):
    approval_id: UUID
    actor: Id
    scope: Id
    decision: Literal["approved", "denied"]
    provider: Id | None = None
    model: Id | None = None
    input_hashes: dict[Id, Hash] = Field(min_length=1)
    timestamp: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def valid_interval(self):
        if self.expires_at <= self.timestamp or (self.provider is None) != (self.model is None):
            raise ValueError("invalid approval interval or partial model identity")
        return self


class TaskSpec(Contract):
    task_id: Id
    source_requirement: Text
    dependencies: list[Id] = Field(default_factory=list)
    outcome: Text
    checks: list[Text] = Field(min_length=1)
    owner_id: Id
    write_scopes: list[Id] = Field(default_factory=list)
    read_scopes: list[Id] = Field(default_factory=list)
    resources: list[Id] = Field(default_factory=list)
    required_capabilities: list[Id] = Field(default_factory=list)
    human_gates: list[Id] = Field(default_factory=list)
    deadline: AwareDatetime
    request_budget: Positive


class AgentSpec(Contract):
    agent_id: Id
    role: Literal["master", "lead", "worker", "reviewer"]
    logical_parent: Id | None
    permitted_children: list[Id] = Field(default_factory=list)
    capabilities: list[Id] = Field(default_factory=list)
    provider: Id
    model: Id
    approval_id: UUID
    workspace: Id
    allowed_tools: list[Id] = Field(default_factory=list)
    write_scopes: list[Id] = Field(default_factory=list)


class TaskPacket(Contract):
    run_id: Id
    epoch: Positive
    task: TaskSpec
    attempt_id: Id
    agent_generation: Positive
    fence: Positive
    inputs: list[ArtifactRef] = Field(default_factory=list)
    reporting_route: Id


class TaskResult(Contract):
    run_id: Id
    epoch: Positive
    task_id: Id
    attempt_id: Id
    agent_id: Id
    agent_generation: Positive
    fence: Positive
    disposition: Literal["submitted", "blocked", "failed", "reconciliation_required"]
    base_revision: Revision
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    changed_paths: list[Id] = Field(default_factory=list)
    test_receipts: list[Text] = Field(default_factory=list)
    blockers: list[Text] = Field(default_factory=list)
    model_requests: Annotated[int, Field(ge=0)]
    requested_model: Id
    effective_model: Id | None = None


class ExecutionEvent(Contract):
    run_id: Id
    epoch: Positive
    sequence: Positive
    kind: Id
    timestamp: AwareDatetime
    task_id: Id | None = None
    agent_id: Id | None = None
    attempt_id: Id | None = None
    causation_id: UUID | None = None
    evidence: Text


class GraphInput(Contract):
    identity: RunIdentity
    tasks: list[TaskSpec] = Field(min_length=1, max_length=1000)
    agents: list[AgentSpec] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def verify_graph(self):
        tasks = {t.task_id: t for t in self.tasks}
        agents = {a.agent_id: a for a in self.agents}
        if len(tasks) != len(self.tasks) or len(agents) != len(self.agents):
            raise ValueError("duplicate task or agent ID")
        roots = [a for a in self.agents if a.logical_parent is None]
        if len(roots) != 1 or roots[0].role != "master" or sum(a.role == "master" for a in self.agents) != 1:
            raise ValueError("exactly one master root required")
        for a in self.agents:
            children = set(a.permitted_children)
            if len(children) != len(a.permitted_children) or children != {
                b.agent_id for b in self.agents if b.logical_parent == a.agent_id
            }:
                raise ValueError("logical children do not match declared hierarchy")
            if a.role in ("worker", "reviewer") and children:
                raise ValueError("leaf role cannot delegate")
            seen = {a.agent_id}
            parent = a.logical_parent
            while parent is not None:
                if parent in seen or parent not in agents:
                    raise ValueError("invalid or cyclic hierarchy")
                seen.add(parent)
                parent = agents[parent].logical_parent
        ready = set()
        for t in self.tasks:
            if t.owner_id not in agents or not set(t.required_capabilities) <= set(agents[t.owner_id].capabilities):
                raise ValueError("missing owner or capability")
            if len(set(t.dependencies)) != len(t.dependencies) or not set(t.dependencies) <= tasks.keys():
                raise ValueError("duplicate or unknown dependency")
        while len(ready) < len(tasks):
            wave = {key for key, task in tasks.items() if key not in ready and set(task.dependencies) <= ready}
            if not wave:
                raise ValueError("task dependency cycle")
            ready.update(wave)
        return self
