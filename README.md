# Graph Execution skills for Codex and Cline

Graph Execution is a set of four installable agent skills for turning a Markdown implementation plan into a dependency-aware backlog, a graph-based team design, and an implementation carried out by the **active CLI's native subagents** (Codex or Cline). The executor is host-aware; it does not shell out to a second CLI.

## Included skills

| Skill | Purpose | Relationship to `gexec` |
| --- | --- | --- |
| [`gexec`](skills/gexec/SKILL.md) | Runs the full workflow in strict sequence: plan decomposition, team design, then implementation. | The orchestrator; it invokes the other three skills in order and gates each handoff on completion and validation. |
| [`critical-path-planner`](skills/critical-path-planner/SKILL.md) | Breaks a Markdown plan into atomic, verifiable tasks and computes dependencies, critical paths, and parallel branches. | Stage 1 inside `gexec`; also usable on its own for planning only. |
| [`backlog-team-designer`](skills/backlog-team-designer/SKILL.md) | Uses task dependencies and graph affinity to propose clusters, ownership, team size, roles, and a capacity-aware execution structure. | Stage 2 inside `gexec`; also usable on its own to design a team from an existing backlog. |
| [`native-plan-executor`](skills/native-plan-executor/SKILL.md) | Executes a plan and its team definition with the active agent as master and native Codex or Cline subagents as workers. | Stage 3 inside `gexec`; also usable independently when a plan and team definition already exist. |

**`gexec` contains and coordinates the other three skills as one workflow.** It invokes them in this order and does not start a later stage while the previous stage is incomplete:

```text
critical-path-planner -> backlog-team-designer -> native-plan-executor
```

The repository includes each constituent skill as a standalone folder so either supported CLI can discover and invoke it directly. `gexec` expects those three skills to be installed and validates their artifacts between stages.

## Requirements

- Codex CLI **or** Cline CLI/SDK with skills and native subagent or team tools enabled. Cline CLI teams are not the same as the VS Code extension.
- Python 3 for the bundled graph and workflow helper scripts.
- For `gexec`, install all four skills together. The stage gate helper is bundled with `gexec`.

## Install

For Codex, clone the repository, then copy the four skill folders into your Codex skills directory. The default is `~/.codex/skills`; if `CODEX_HOME` is set, use `$CODEX_HOME/skills` instead.

```bash
git clone https://github.com/Trochez/graph-execution.git
cd graph-execution

SKILLS_DIR="${CODEX_HOME:-$HOME/.codex}/skills"
mkdir -p "$SKILLS_DIR"
cp -R skills/gexec skills/critical-path-planner \
  skills/backlog-team-designer skills/native-plan-executor \
  "$SKILLS_DIR/"
```

If a skill with one of these names already exists, review or back it up before copying so you can preserve any local changes. Restart or refresh the host's skill discovery if the new skills do not appear immediately.

**Cline CLI / Windows PowerShell:**

```powershell
git clone https://github.com/Trochez/graph-execution.git
New-Item -ItemType Directory -Force "$HOME\.cline\skills" | Out-Null
Copy-Item -Recurse -Force .\graph-execution\skills\* "$HOME\.cline\skills\"
```

Cline supports global skills under `~/.cline/skills/` and project-scoped skills under `.cline/skills/`. In CLI interactive mode, inspect `/settings` to enable `spawn_agent` and `teams`. Start a complex implementation in an agent-team session with `/team`, then instruct the active coordinator to use `native-plan-executor` on the specific plan and team definition. Check [Cline's agent teams documentation](https://github.com/cline/cline/blob/main/docs/cli/agent-teams.mdx).

## Use

### Run the complete plan-to-implementation workflow

In Codex, provide a Markdown plan and invoke `gexec`, for example:

> Use `$gexec` to implement `docs/implementation-plan.md` in this workspace.

The orchestrator produces and validates a task backlog, produces and validates a team definition, then starts implementation. It keeps stage artifacts in a run-specific directory and reports stage status, artifacts, changes, and verification evidence. The execution stage may ask you to confirm a leaf-agent model before dispatch; it saves a confirmed choice for reuse and requests renewed confirmation on the first invocation of each new calendar month.

### Run one stage by itself

- **Plan only:** invoke `$critical-path-planner` with a `.md` plan. It writes planning artifacts and stops without launching implementation agents.
- **Design a team:** invoke `$backlog-team-designer` with an existing backlog or structured task file. It writes a team definition but does not launch the team.
- **Execute an existing design:** invoke `$native-plan-executor` with the plan, backlog, and team definition. It carries out the plan with the **active host's** native subagents/team members and verifies integrated results.

## How it works

1. **Decompose and schedule.** `critical-path-planner` maps plan requirements to atomic tasks, records dependency reasons, checks the directed acyclic graph, and computes critical paths and readiness waves. Its scripts validate and analyze the task DAG.
2. **Cluster and staff.** `backlog-team-designer` distinguishes dependency edges from task-affinity and agent-coordination graphs. Its helper proposes task communities; the skill then evaluates team size, roles, ownership, capacity, handoffs, and alternatives. The graph helper informs the design but does not claim to mathematically optimize staffing.
3. **Execute and integrate.** `native-plan-executor` makes the active agent the master for dispatch, integration, and final verification. Native Codex or Cline agents work on assigned tasks. The executor detects the active host through live tool capabilities and selects the matching protocol; ambiguous or unavailable native delegation blocks dispatch. Before dispatch, it discovers available models and requires user confirmation of the proposed lowest-hierarchy model when the saved approval is missing, out of date, or unusable. It does not silently fall back to another model.
4. **Gate the sequence.** `gexec` completes and validates each stage before beginning the next, records artifacts and fingerprints, and supports reconciliation and resumption. If a stage remains invalid after its focused repair, it stops with a resumable blocker rather than skipping ahead.

Each standalone skill has its own `SKILL.md`, references, and helper scripts inside `skills/<skill-name>/`. See those files for artifact schemas, detailed policies, and limits.

## Repository layout

```text
skills/
  gexec/
  critical-path-planner/
  backlog-team-designer/
  native-plan-executor/
```
