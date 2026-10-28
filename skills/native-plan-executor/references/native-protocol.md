# Native execution protocol

## Preflight and execution record

Use the current tool schema as the operational contract. Native interfaces and limits vary; do not assume a public API example establishes this session's capabilities. Check existing agents and current activity before dispatch. Count the master and every active lead/leaf according to the live capacity rule. In the authoring runtime there are four active slots including root, shared across the tree; discover the actual limit when this skill is used instead of treating four as universal.

Establish one implementation workspace using the repository's instructions and isolation convention. Preserve existing user changes; identify each task's allowed files/resources. Shared working directories require explicit ownership even when agents have separate conversations. Worktrees, if used, require integration of tested commits/patches before downstream readiness. Do not commit/push/deploy merely because local implementation was requested.

Create a fresh run directory under `.native-plan-executor/<plan-slug>-<run-id>/` in the execution workspace, or the user's destination. Keep `execution.json` as a compact snapshot and `events.jsonl` as significant dispatch/result/verification events. These are implementation records, not authority grants or substitutes for native runtime state. Do not write `.omx/state`, Team lifecycle files, or Ultragoal ledgers unless a separately active workflow explicitly owns them. No hidden goal creation is needed.

Master owns these records; leads report upward rather than editing them. Store:
- Plan/backlog/team paths and content fingerprints, workspace, completion unit and source task ID mapping.
- Declared hierarchy, role/capability mapping, reporting routes, fixed assignments, concurrency constraints and temporary scheduling phases.
- For each defined agent: definition ID, native identity, parent native identity, supported role, requested model, observed effective model if exposed, and status. If effective routing is not exposed, record `unknown`, not a fabricated confirmation.
- For each task: owner, dependencies, write scopes, acceptance criteria, state, blocker, changed artifacts and verification evidence.

On resume, reread source artifacts and inspect the live agent tree and actual changes. Reconcile task evidence before dispatching again. Changed inputs invalidate affected downstream assumptions; do not silently treat stale completed tasks as valid. Records and matching names alone never establish a live agent's identity or ownership.

## Model policy and hierarchy

The supplied team determines who exists and who reports to whom. Map its root coordinator/master to the active agent when compatible. If it specifies a separate immutable coordinator beneath another root, preserve both and count both. A master-only definition cannot satisfy a requested subordinate implementation team without a revised definition; do not invent performers.

Classify leaves from declared logical agent reports, not cluster depth, physical proxy-spawn parentage or task labels. Every subordinate with no logical agent reports uses the user-confirmed model from the saved model selection policy, even when it executes multiple tasks or acts as reviewer. Existing leaf assignments that differ from the confirmed choice must be mapped transparently without changing responsibilities. If a fixed team/role constraint forbids the approved model, resolve that incompatibility with the user before dispatch. Never silently substitute a different model on a difficult task.

Follow [model-selection.md](model-selection.md) for discovery, balanced-value recommendation, initial/monthly confirmation and persistence. This supersedes the former cheapest-on-every-run policy and unconfirmed gpt-6-luna fallback. Record the confirmed config receipt and inventory/capability check in each execution record; keep the static user-wide selection separate from run state. Public pricing and runtime-supported IDs are evidence with different scopes, not proof of account access or billing equivalence.

For the authoring native tool, a leaf call has this argument shape:

```json
{
  "task_name": "backend_leaf",
  "agent_type": "executor",
  "model": "<confirmed-model-id>",
  "fork_turns": "none",
  "message": "Self-contained assignment with source requirements, inputs, ownership, checks, reporting route and stop condition"
}
```

Names are examples; actual tasks must use the supplied definition. Explicit model overrides require `fork_turns: "none"` here. Do not set reasoning effort unless the user/team or supported role requires it. An explicit role may pin settings; when precedence cannot satisfy the leaf policy, use a permitted role mapping with the same required capability or report the conflict. Do not modify user-wide agent configuration to force routing.

For a declared logical non-leaf lead, default to inherited model/context where supported. Give it exactly the defined subtree and shared capacity budget. Its prompt authorizes only the defined coordination responsibilities and, where its governing role permits, planned child spawning. If a role guard prohibits child spawning, the lead reports dispatch recommendations upward and the master creates the defined agents directly. Preserve the logical reporting/ownership graph and separately record actual native parentage; do not claim the physical hierarchy was preserved. Leads with a no-orchestration restriction remain within that restriction: master handles scheduling and routing while retaining their allowed review/integration responsibilities. If even this cannot preserve a mandatory responsibility, report the conflict rather than bypass instructions. Logical clusters can remain nested within a flat native spawn tree.

## Dispatch packet and ownership

Send each agent only the relevant, sufficient context:

```text
Definition agent ID, native reporting parent and role:
Task IDs and source requirements:
Workspace and allowed write paths/resources:
Prerequisite artifacts and verified contracts:
Required outcome and acceptance checks:
Shared-write reservations and other active owners:
Available tools/capabilities and applicable repository rules:
Completion unit and stop condition:
Report format: task IDs, changed files, checks with results, artifacts, blockers and handoff.
```

Tell performers they share a workspace, must not revert others' edits, and must escalate ownership conflicts rather than editing outside scope. Leaf packets explicitly prohibit spawning children. Designated leads get a subtree packet instead, with their allowed children, ownership, reporting responsibilities and shared slot budget. Keep each packet self-contained when no history is inherited.

Shared-write reservations cover files and non-file resources (schemas, environment state, migrations, deploy targets) actually touched. A dependency edge alone does not make simultaneous shared writes safe. Reserve resources before dispatch and release them only after the write has stopped and results are inspected. A finished task must hand off the artifact/version and proof needed by dependents.

## Coordination and choreography

Use the active native equivalents of:

| Tool | Purpose |
|---|---|
| `spawn_agent` | Create a defined agent and capture its returned native identity |
| `send_message` | Deliver context or a correction; does not start an idle agent turn |
| `followup_task` | Give an existing idle/completed agent its next bounded assignment and start a turn |
| `list_agents` | Inspect known identities/status; avoid dispatching duplicate work |
| `wait_agent` | Wait for result/mailbox activity; inspect messages, not only the status notification |
| `interrupt_agent` | Stop an agent's current turn before changing its write assignment |

Call native collaboration tools directly when they are not exposed inside a general execution tool. Do not invent a missing tool or simulate parallel agents in prose. Avoid repeated status polling; wait for messages, with progress updates at the user's requested cadence. In this environment keep individual waits at or below 60 seconds so updates remain possible.

Master controls dispatch for the defined team. A lead may spawn only its assigned children when supported; otherwise master proxy-spawns those agents and records both their logical lead and actual native parent. Within a logical subtree, its lead recommends ready work and reports results upward; native dispatch remains with the authorized spawner. Master resolves cross-subtree contracts, resources and integration. Cross-team messages may clarify contracts; they must not secretly reassign another lead's owner. Global slot reservations are agreed before any nested spawn to prevent leads each consuming the full capacity.

Schedule task states as `pending -> ready -> assigned -> in_progress -> verifying -> done`. Readiness requires prerequisites' verified artifacts, available assigned owner, write reservations and required external gates. A result can transition to `blocked` or back to a bounded repair assignment. Native thread status is separate from task status. Do not call a task done solely because an agent completed a turn.

Advance independent ready work as soon as capacity permits instead of imposing an unnecessary global barrier. Join branches only when their actual dependencies and integration checks are satisfied. Release idle capacity according to available runtime lifecycle tools; do not invent a close operation. If inactive threads still consume capacity, account for that fact and reuse existing agents only where their defined roles/ownership permit it.

## Errors and recovery

A failed check first gets a bounded diagnosis/repair through its assigned leaf using the same model. After one focused retry fails for the same unresolved cause, the lead/master must reassess evidence, scope and dependencies before another attempt; do not loop or spawn redundant substitutes. Decompose or clarify within the plan when safe, preserving ownership and acceptance. Any replacement model requires explicit user confirmation through the selection gate; do not rewrite the saved approval from a retry. Leads may diagnose/integrate within their defined responsibilities; they must not silently absorb the whole leaf backlog to bypass the routing policy.

For capacity exhaustion, wait for existing work or activate the same defined agents in phases, preserving assignments and prerequisites. Phases are authorized by default unless simultaneous staffing is explicit. If the definition requires unavailable simultaneous agents, a mandatory unsupported responsibility, model or native hierarchy capability that master proxy-spawning cannot satisfy, report the exact conflict and feasible revision as a proposal; do not execute a materially changed team. Without native delegation, return a concrete blocker; do not switch to shell/tmux orchestration.

For a changed assignment or write conflict, interrupt the old active writer when necessary, confirm it stopped, inspect resulting edits, and only then transfer ownership. A queued message is not proof that an active writer stopped. On user stop, cease dispatch, interrupt this run's active descendants through known native identities, record partial results, and leave unrelated agents and artifacts untouched.

## Completion gate

Inspect child changes and run relevant project checks in the integrated workspace. A leaf reviewer still uses the designated low-cost model; independent review must preserve separation from authoring where the plan requires it. Failures return to the responsible owner with evidence. Do not add unrelated cleanup or features.

Completion requires every in-scope task's acceptance proof, integrated results, required review/checks, no pending in-scope work and explicit final status for all known run agents. Before concluding, confirm no this-run descendant is still mutating the workspace; use status tools and completion messages or interruption as appropriate. Do not claim that an idle context was destroyed if no lifecycle tool supports that.

Report completed/blocked tasks, changed files, fresh check commands/results, actual team hierarchy, requested leaf model and any observable routing limits. Distinguish runtime model selection from monetary savings: without usage/rates, do not invent cost totals. Preserve source plan/team files unless their edit was explicitly part of the task.

## Supporting documentation

The active native schema takes precedence for this environment. Official Codex documentation supports per-agent model settings and model configuration: [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents). Configuration limits can differ from the live tool's root-inclusive limit: [Configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference). Do not transfer Responses API concurrency or model restrictions to this native runtime.
