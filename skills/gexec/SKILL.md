---
name: gexec
description: Use when a Markdown plan should proceed through critical-path-planner, backlog-team-designer, and native-plan-executor as strictly sequential stages with validated handoffs and resumable execution.
---

# Gexec

Accept one `.md` implementation plan and run these installed skills in order:

1. `$critical-path-planner`
2. `$backlog-team-designer`
3. `$native-plan-executor`

**One stage at a time.** The previous skill must finish its work, complete its checks, publish validated artifacts, and have no pending stage work before the next skill begins. Partial output files or a completed agent turn are not a stage-completion gate. Parallel work inside the current skill remains subject to that skill's rules.

## Preflight

Resolve the source plan, target workspace and governing instructions. Verify all three required skills are installed, discovering their actual `SKILL.md` paths; if missing, search for a moved installation, then report a blocker if still absent. Do not replace a missing skill with a homegrown equivalent or shell command named after the skill.

This wrapper invocation requests the full chain, including local implementation at stage 3. Preserve source scope and authorization boundaries; it does not imply deployment, pushing commits or unrelated external actions. Creating or inspecting this wrapper alone does not launch an application plan.

Read [the sequential stage protocol](references/stages.md). Create a fresh run directory and initialize its manifest with the bundled gate helper, or reconcile an explicitly resumed run. Dependency availability and destination checks may happen before stage 1; later-stage analysis, staffing decisions and implementation may not.

## Run the stages

The active master coordinates the sequence. Load and apply each constituent skill's actual instructions when its turn starts. Do not dispatch different stages concurrently, prepare speculative downstream work, or run a later stage while the current one repairs artifacts.

- **Stage 1:** Apply `$critical-path-planner` to the original Markdown plan. Validate the complete task/dependency bundle and source coverage. It produces the backlog; it does not design or launch the execution team.
- **Stage 2:** Only after stage 1's verified completion, apply `$backlog-team-designer` to that run's validated backlog/tasks and original constraints. Validate complete ownership and a feasible team definition. It does not launch implementation agents.
- **Stage 3:** Only after stage 2's verified completion, apply `$native-plan-executor` using the original plan, the exact validated backlog and team definition. Follow its native-agent, model-routing, ownership and verification policies through full implementation.

Keep each stage's outputs in its own run subdirectory. Record actual artifact paths and fingerprints; never choose another run's files by filename alone. Use the protocol's semantic checks before marking a stage completed. The helper guards manifest transitions and stale files, not actual agent runtime behavior; the master must verify no work or writers remain from the finishing stage.

## Failure, resume and completion

Allow one focused repair within a failed stage and revalidate it. Keep successors unstarted. If repair is unsuccessful, record a blocked stage and stop with evidence and a resumable handoff; do not loop or skip ahead.

On resume, reconcile live agents and partial changes first. Reuse a completed stage only when its inputs, outputs and completion evidence remain valid. Restart from the earliest affected stage after invalidating downstream receipts. Preserve artifacts and implementation changes; reconcile them rather than deleting or blindly replaying work.

Finish only when all three stages are completed and the executor's integrated checks pass. Report the source plan, stage statuses, artifact links, implementation changes and verification results. If blocked, identify the failed gate and next required information/action without describing the full chain as complete.
