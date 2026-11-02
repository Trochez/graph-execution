# Cline native execution protocol

This protocol applies **only when** [runtime-selection.md](runtime-selection.md) confirms the active host is a Cline CLI/SDK session. Use the Cline native team/subagent tools directly. Keep the same plan/backlog/team constraints, source task IDs, run records, exclusive write ownership, dependency graph, verification and completion gates defined in `SKILL.md`. Do **not** start `codex` or a second `cline` process, reimplement agents via shell, or treat Cline IDs as Codex IDs.

## Preflight and model routing

Inspect Cline's **live tool schemas** for capabilities and record the actual mode: `cline-team` or `cline-subagent`. CLI teams are documented for Cline CLI, SDK and Kanban, not equivalently for the VS Code/JetBrains extensions. A Cline CLI team may need to be initiated with `/team` at session start; if team tools are not exposed, request that the user enable `teams` / `spawn_agent` in `/settings` and restart the workflow. Do not send `/team` as a shell command or assume a prompt can retroactively grant missing tools.

Model selection follows [model-selection.md](model-selection.md), using an explicit Cline config path:

```bash
python3 <skill-dir>/scripts/model_policy.py status --config ~/.cline/native-plan-executor/model-policy.json --available <verified-model-ids...>
```

On Windows PowerShell, use `python` if `python3` is unavailable and `--config "$HOME\.cline\native-plan-executor\model-policy.json"`. Do not save a choice until the user confirms it. Record available provider, exact model ID, advertised inventory coverage and any exposed **effective** routing. Cline configured agent profiles under `<workspace>/.cline/agents/` or `~/.cline/agents/` may specify `providerId` and `modelId`. Generic `spawn_agent` otherwise inherits its parent configuration. Never assume `team_spawn_teammate` accepts a `model` argument merely because Codex's tool does: check the actual schema. If the approved leaf model cannot be enforced for the chosen mode, pause that dispatch and report the blocker or obtain an explicitly approved feasible mapping.

## Team mode: persistent, plan-oriented delegation

Prefer this mode for multi-stage implementations with multiple defined agents, messages, dependencies or resumption. The actual Cline team tools can include:

| Native Cline capability | Purpose |
|---|---|
| `team_spawn_teammate` | Create a teammate associated with its defined role |
| `team_task` | Track a source task, owner, dependency and status |
| `team_run_task` | Start a teammate's assigned work |
| `team_status` / `team_list_runs` | Observe live teammates and ongoing runs |
| `team_await_runs` | Await completion before checking evidence |
| `team_send_message` / `team_read_mailbox` | Communicate instructions, findings and handoffs |
| `team_cancel_run` / `team_shutdown_teammate` | Stop this run's workers when permitted |
| `team_mission_log` | Native coordination log, **not** the authority for acceptance |

Treat these names as documentation; use only the **actual available** tools and their current argument schema. The current root is the master, so never spawn a second coordinator. Map each defined agent ID to a native teammate ID and task IDs to native task/run IDs. Record both logical parentage and actual Cline team ownership; Cline's peer-to-peer teammates are **not** a physical Codex-like subagent tree. Preserve reporting logic and role guards through task packet instructions and master-controlled scheduling.

For each ready task: verify prerequisite evidence; reserve files and non-file shared resources; publish the bounded task/owner/acceptance requirements; start the assigned teammate's run; await or observe results; inspect diff/artifacts and run verification; release write reservations only after work stops. Keep states `pending -> ready -> assigned -> in_progress -> verifying -> done`, with explicit `blocked` and bounded repair transitions. Reuse defined teammates rather than creating a teammate per task. Advance independent branches when capacity and write ownership allow. Cline persistent team state is **not** a substitute for the master-owned `.native-plan-executor/<run>/execution.json` and `events.jsonl`.

## Subagent mode: bounded delegation only

When the live runtime exposes Cline `spawn_agent` or configured `subagent_<name>` without team tools, use it **only** for independent bounded assignments with no mandatory persistent team coordination. The call returns the subagent result to its parent; do not invent a persistent teammate ID, mailbox, list/wait API or asynchronous thread. Record the task/result, usage evidence if available, and actual subagent tool identity in the run record. A team definition requiring durable lead/leaf communication, parallel active writers, or persistent handoffs is **blocked** in this mode unless the live tool proves those capabilities.

## Ownership, failures and completion

Give every performer its defined agent ID, task IDs, source requirements, workspace, permitted write scopes, input artifacts, accepted model, dependency evidence, checks and exact reporting format. Leaves cannot delegate. Non-leaf leads may coordinate only their declared subtree when tools/role guards allow; if peer-to-peer team mode cannot encode the logical hierarchy physically, master retains dispatch and records the mapping rather than pretending to preserve nesting.

On conflicts, stop the former writer and inspect its edits before transferring ownership. On failure, perform one bounded diagnosis/repair, then reassess instead of spawning duplicate agents. A stopped/idle Cline run is not a passed test. Completion requires fresh integrated checks and proof for each task; confirm no run teammate is still writing. On resume, reconcile native team runs and filesystem changes; never rely solely on saved names/status.

Report task outcomes, changed files, fresh tests, selected runtime, actual Cline identities, approved requested model and any observed/unknown effective model, plus blockers. Do not claim model overrides or parallelism that Cline's live interface did not confirm.

## Official references

- [Cline CLI agent teams](https://github.com/cline/cline/blob/main/docs/cli/agent-teams.mdx)
- [Cline SDK multi-agent and agent profiles](https://github.com/cline/sdk-skill/blob/main/skill/cline-sdk/references/multi-agent/REFERENCE.md)
- [Cline CLI configuration](https://github.com/cline/cline/blob/main/docs/cli/cli-reference.mdx)
- [Cline skills](https://github.com/cline/cline/blob/main/docs/customization/skills.mdx)
