---
name: native-plan-executor
description: Use when asked to start or continue implementation of a specified plan using an existing team definition, with a master agent coordinating native Codex subagents and user-approved leaf models.
---

# Native Plan Executor

Execute the supplied plan with the supplied team definition. The active agent is the master: it owns dispatch, integration, final verification and reporting. Native Codex subagents perform the defined subordinate work. Creating this skill does not itself authorize execution of an unrelated plan.

## Initial leaf-model selection and approval

Before dispatching any implementation or review agent, follow [the saved model selection policy](references/model-selection.md). Discover the models exposed by the active environment and record inventory coverage. Read the plan/team's leaf capability needs, then inspect the user-wide confirmed selection.

On first use, the first invocation of a new calendar month, or when the saved model is unavailable/incompatible, compare feasible candidates for balanced value: cost, capability, speed and likely retry/supervision effort. Present the proposal with evidence and uncertainty, and ask the user to confirm it or specify another available model. Wait for the answer before saving a selection or spawning agents. A previous generic preference for cheap models is not confirmation of a newly proposed model.

Persist only the confirmed choice in `$CODEX_HOME/native-plan-executor/model-policy.json` (or `~/.codex/native-plan-executor/model-policy.json` when unset), separate from global Codex model settings and execution records. Reuse it across projects within the confirmed calendar month, while checking current availability and hard capability requirements each run. Monthly review is triggered by invocation, with no background scheduler. Even an unchanged monthly recommendation requires renewed user confirmation. Do not silently fall back to a different model.

## Bind the execution inputs

Read the plan, backlog, team definition and applicable project instructions. Accept Markdown or structured team artifacts, including `backlog-team-designer` output without requiring that skill. Resolve paths, task IDs, prerequisites, acceptance criteria, assigned owners, role hierarchy, shared-write scopes and concurrency limits. Identify the root/master role and map it to the active agent; do not add a second master or duplicate the defined coordinator.

Follow explicit assignments and logical reporting lines. The master may spawn defined agents directly when their leads cannot spawn, while preserving the logical team hierarchy and recording the actual native tree. Treat clusters as task grouping unless the definition actually assigns lead agents. Do not regenerate the backlog or redesign the team. Ask only for missing inputs or conflicts that prevent a faithful launch; continue independent authorized work where feasible.

Read [the native execution protocol](references/native-protocol.md) before spawning. It defines routing, communication, task transitions, recovery and completion evidence.

## Route models and roles

Use the model resolved through the initial approval gate for every lowest-hierarchy agent, including leaf reviewers. The confirmed user choice takes precedence over a recommendation based on price. A prompt naming a model does not route it; pass the exact approved ID through the native model setting. No fixed Luna fallback bypasses confirmation.

Use the running master model for coordination. Non-leaf leads inherit the master model unless the definition explicitly specifies another supported model. A role with no subordinate agents in the declared logical team is a leaf even if its title says “lead.” Physical proxy spawning does not change that classification. Leaf agents cannot delegate. A designated lead coordinates only its defined subtree. When its role cannot spawn, it sends dispatch recommendations to the master; the master performs native spawning and scheduling without overriding the role guard.

Inspect the live tool schema and available model/role inventory. This runtime supports explicit leaf model requests, `model: "<confirmed-model-id>"`, with `fork_turns: "none"`; provide complete bounded context. Include a supported `agent_type`; use `executor` for ordinary implementation, not Team-runtime `worker`. If a role/configuration prevents the required model selection, resolve an allowed equivalent mapping or report the blocker. Never silently substitute an inherited, cheaper, or more expensive model for the confirmed choice.

## Execute through native agents

Use native spawn, messaging, follow-up, status and wait tools directly. Do not replace them with tmux teams, external orchestration, shell-launched Codex processes or simulated agents. Preserve the logical hierarchy and task ownership while scheduling within actual runtime capacity. Phased activation is allowed unless the definition explicitly requires simultaneous staffing; mandatory simultaneous staffing that exceeds capacity is a conflict to report.

Dispatch ready tasks with exclusive write ownership and observable completion criteria. Reuse the defined agents for their next tasks; do not spawn a new agent per task or duplicate work because a message is delayed. Integrate completed prerequisites before releasing dependent work. Resolve shared-file reservations and interface handoffs explicitly.

## Verify and finish

Persist a small master-owned execution record outside OMX runtime state, as described in the protocol. Track requested models, actual native identities, ownership, task status and verification evidence. Do not claim requested model routing proves an undisclosed effective model.

Continue through the authorized completion unit—by default all tasks in the supplied plan—until implemented and verified, explicitly blocked, or stopped by the user. Run the relevant integration checks after child results; child success alone is not final proof. Report changed files, checks and results, completed/blocked tasks, team/model routing and remaining limits. Do not claim completion while any required task lacks evidence.
