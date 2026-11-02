---
name: native-plan-executor
description: Implement a specified plan and team definition with native subagents from the active Codex or Cline CLI, preserving user-approved leaf-model routing and verification.
---

# Native Plan Executor

Execute the supplied plan with the supplied team definition. The current host agent is the master: it owns dispatch, integration, final verification and reporting. Its **current native runtime** (Codex CLI or Cline CLI) executes subordinate work. Do not launch a different CLI to simulate a native subagent. Creating this skill does not itself authorize implementation of an unrelated plan.

## Resolve active CLI runtime before model selection or delegation

Follow [runtime selection](references/runtime-selection.md). Inspect the actual session's available native tool schemas and trusted host metadata. Select **Codex**, **Cline team**, or **Cline subagent** only when there is positive evidence; a binary on `PATH`, a project directory, or `CODEX_HOME`/`CLINE_*` variables alone cannot establish the active host. If tools are unavailable or ambiguous, ask for an explicit host selection and check its native capabilities; fail closed when required delegation is unavailable. Never silently create an external Codex or Cline process.

For Codex use [native-protocol.md](references/native-protocol.md); for Cline use [cline-protocol.md](references/cline-protocol.md). They share the same source plan, DAG, write ownership, verification and run-record requirements. The active host's live tool schema takes precedence over examples in either protocol.

## Initial leaf-model selection and approval

Before dispatching any implementation or review agent, follow [the saved model selection policy](references/model-selection.md). Discover the models exposed by the active environment and record inventory coverage. Read the plan/team's leaf capability needs, then inspect the user-wide confirmed selection.

On first use, the first invocation of a new calendar month, or when the saved model is unavailable/incompatible, compare feasible candidates for balanced value: cost, capability, speed and likely retry/supervision effort. Present the proposal with evidence and uncertainty, and ask the user to confirm it or specify another available model. Wait for the answer before saving a selection or spawning agents. A previous generic preference for cheap models is not confirmation of a newly proposed model.

Persist only the confirmed choice in the **host-specific policy location** described in [model-selection.md](references/model-selection.md): the existing Codex location remains unchanged; Cline uses its own `~/.cline/native-plan-executor/model-policy.json`. Pass `--config` explicitly on Cline. Reuse a host's confirmed choice across projects for the confirmed month, while checking model availability and hard capability requirements on every run. Monthly review is triggered by invocation, with no background scheduler. Even an unchanged monthly recommendation requires renewed user confirmation. Do not silently fall back to a different model.

## Bind the execution inputs

Read the plan, backlog, team definition and applicable project instructions. Accept Markdown or structured team artifacts, including `backlog-team-designer` output without requiring that skill. Resolve paths, task IDs, prerequisites, acceptance criteria, assigned owners, role hierarchy, shared-write scopes and concurrency limits. Identify the root/master role and map it to the active agent; do not add a second master or duplicate the defined coordinator.

Follow explicit assignments and logical reporting lines. The master may spawn defined agents directly when their leads cannot spawn, while preserving the logical team hierarchy and recording the actual native tree. Treat clusters as task grouping unless the definition actually assigns lead agents. Do not regenerate the backlog or redesign the team. Ask only for missing inputs or conflicts that prevent a faithful launch; continue independent authorized work where feasible.

Read the selected host's execution protocol before spawning. It defines routing, communication, task transitions, recovery and completion evidence.

## Route models and roles

Use the model resolved through the initial approval gate for every lowest-hierarchy agent, including leaf reviewers. The confirmed user choice takes precedence over a recommendation based on price. A prompt naming a model does not route it; pass the exact approved ID through the native model setting. No fixed Luna fallback bypasses confirmation.

Use the running master model for coordination. Non-leaf leads inherit the master model unless the definition explicitly specifies another supported model. A role with no subordinate agents in the declared logical team is a leaf even if its title says “lead.” Physical proxy spawning does not change that classification. Leaf agents cannot delegate. A designated lead coordinates only its defined subtree. When its role cannot spawn, it sends dispatch recommendations to the master; the master performs native spawning and scheduling without overriding the role guard.

Inspect the live tool schema and available model/role inventory. **Codex:** where the native spawn interface supports explicit model selection, use the confirmed `model` ID and any required context flags exactly as specified by its live schema; an `executor` role is only a Codex example, not a Cline role. **Cline:** check whether the chosen team or subagent tool supports exact per-agent model routing. Cline configured agent profiles can set `providerId` and `modelId`; generic subagents otherwise inherit the parent configuration. Do not claim a task prompt changes the actual model. When a required leaf-model override cannot be enforced, stop affected dispatch and report the blocker rather than silently inheriting the master's model.

## Execute through native agents

Use the selected host's **native** delegation, messaging/status and wait equivalents directly, following its supported lifecycle. Do not replace them with tmux teams, external orchestration, shell-launched Codex/Cline processes or simulated agents. Preserve the logical hierarchy and task ownership while scheduling within actual runtime capacity. Phased activation is allowed unless the definition explicitly requires simultaneous staffing; mandatory simultaneous staffing that exceeds capacity is a conflict to report.

Dispatch ready tasks with exclusive write ownership and observable completion criteria. Reuse the defined agents for their next tasks; do not spawn a new agent per task or duplicate work because a message is delayed. Integrate completed prerequisites before releasing dependent work. Resolve shared-file reservations and interface handoffs explicitly.

## Verify and finish

Persist a small master-owned execution record outside OMX runtime state, as described in the protocol. Track requested models, actual native identities, ownership, task status and verification evidence. Do not claim requested model routing proves an undisclosed effective model.

Continue through the authorized completion unit—by default all tasks in the supplied plan—until implemented and verified, explicitly blocked, or stopped by the user. Run the relevant integration checks after child results; child success alone is not final proof. Report changed files, checks and results, completed/blocked tasks, team/model routing and remaining limits. Do not claim completion while any required task lacks evidence.
