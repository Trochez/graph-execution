# Sequential stage protocol

## Run identity and gates

Use the target implementation workspace and the user's destination, or a fresh `.gexec/<plan-stem>-<run-id>/` directory. Keep the original plan unchanged. Suggested subdirectories are `01-backlog/`, `02-team/`, `03-execution/`; pass them as explicit output destinations to the constituent skills. Record any actual alternate locations rather than assuming paths.

Resume existing runs from their recorded directory without relocating them. Only the active master writes `pipeline.json`. This is a wrapper record, not OMX runtime state or a permission grant. Do not modify `.omx/state`, Team artifacts or goal ledgers. Maintain one active wrapper run for the same work; before resuming or starting a duplicate, inspect existing run records and relevant known native agents. Do not interrupt unrelated agents.

Read each installed skill as the stage begins and perform its actual workflow. A helper script or a Markdown label does not invoke a skill. The wrapper owns stage barriers and handoff validation; the constituent skills own decomposition, team design and native execution. Do not duplicate those algorithms here.

Initialize and advance gates through the bundled Python CLI (resolve `<skill-dir>`):

```bash
python3 <skill-dir>/scripts/stage_gate.py init <run>/pipeline.json --plan <plan.md>
python3 <skill-dir>/scripts/stage_gate.py start <run>/pipeline.json --stage critical-path-planner
# Apply the actual skill, wait for its work to finish, then verify the stage gate.
python3 <skill-dir>/scripts/stage_gate.py finish <run>/pipeline.json --stage critical-path-planner --outputs <backlog.md> <tasks.json> <dag-analysis.json> --evidence "Completed workflow; coverage reviewed; DAG check passed; no pending stage work"
```

Repeat `start` and `finish` with the exact names `backlog-team-designer` and `native-plan-executor`, in order. Use concrete evidence, including relevant check commands/results and report paths. The helper requires nonempty evidence but cannot prove that prose is true. Never substitute an assertion for inspecting actual artifacts, runtime activity and check output.

Each start snapshots source-plan and predecessor output fingerprints. Only the active stage can finish or fail. Every predecessor must be complete with unchanged inputs/outputs. A finish requires unchanged inputs, existing output files and evidence. It clears the active stage only after the master has established the semantic gate below. The helper is single-writer support; it does not coordinate concurrent masters, enforce thread termination or prevent someone calling unrelated tools outside the workflow.

## Stage 1 — task/dependency handoff

Inputs: original `.md` plan, governing repository instructions and original constraints.

Invoke/apply `$critical-path-planner`. Gate:
- Full workflow finished, any stage agents/processes joined and no pending work/writers.
- `backlog.md`, `tasks.json`, `dag-analysis.json` exist and are parseable where structured.
- Every in-scope requirement maps to tasks and observable completion proofs.
- Task IDs/dependency references are valid; DAG computation succeeds; critical/parallel branches and uncertainty are represented.
- No unresolved blocker that prevents a usable backlog; no source-plan changes or implementation-agent launch.

Run the planner's own DAG helper for the generated tasks if its successful evidence is not fresh. Record the actual source requirement coverage inspection and command result. A document called 'backlog' alone is insufficient.

The stage 1 receipt contains all three artifacts. Stage 2 consumes those exact paths; pass runtime/role/capacity constraints already known from the user/environment without doing stage 2's design early.

## Stage 2 — team handoff

Inputs: verified stage 1 bundle and original plan/constraints. Apply `$backlog-team-designer`.

Gate:
- Full workflow finished, stage activity quiescent.
- `team-definition.md`, `team-definition.json`, `task-graph.json`, `graph-analysis.json` exist; structured files parse.
- Original task IDs, requirements and dependency direction preserved; every task assigned once to a leaf cluster and accountable owner.
- Child clusters partition their parent; owners/roles resolve; total and concurrent team counts include the master/coordinator.
- Proposed schedule respects prerequisites, skills, shared writes, reviews and runtime capacity. Carry native executor's required supported-model/role constraints as compatibility checks, without spawning implementation agents.
- Critical-path backlog and original plan remain unchanged; team ready for execution with no unresolved material launch blocker.

Rerun the designer's graph helper if needed to establish fresh valid graph evidence. If it discovers a necessary new technical dependency or missing task, do not silently edit the stage 1 handoff or start implementation. Record the discrepancy, stop downstream work, and return to the earliest affected stage through invalidation/reconciliation. Routine same-stage presentation fixes do not require a new dependency graph.

Record all four output paths and validation evidence. A provisional 'recommended team' without ownership/runtime fit does not pass.

## Stage 3 — implementation completion

Inputs: original plan, validated stage 1 backlog/tasks and stage 2 team. Apply `$native-plan-executor` in the active master lane. This explicit wrapper instruction supplies the separate execution handoff required by the two planning skills; it does not make those planning skills implement anything.

Preserve its current native model selection, logical reporting, master proxy spawning, capacity phases, write ownership and bounded repair rules. No wrapper-specific agent hierarchy or global model-config changes are needed. Native subagents may execute ready tasks in parallel inside stage 3; that does not permit concurrent planning stages.

Gate:
- All in-scope tasks implemented, integrated and verified according to the plan.
- Required tests/checks/review results inspected in the integrated workspace.
- No pending task or run agent still mutating files; actual run identities/status checked.
- Executor's final `execution.json` is complete, with task/check evidence; final implementation report exists.

Store a wrapper `03-execution/result.md` summarizing changed files, actual check commands/results, task completion, native run record path and remaining limitations. Finish the stage with that report and the final executor record as outputs. Do not fingerprint the entire mutable repository as an immutable handoff; on later resume, recheck implementation proof/current workspace under the executor's reconciliation protocol.

## Failure and repair

On first failure, keep the same stage active and successors unstarted. Record the failure and focused repair attempt in its evidence/report; perform at most one focused repair, then revalidate. A failed gate is not permission to run downstream logic to see whether it 'works anyway'. If a constituent skill already attempted its focused repair for the same cause, count it as the wrapper's repair; do not multiply nested retry allowances.

If still blocked, run:

```bash
python3 <skill-dir>/scripts/stage_gate.py fail <run>/pipeline.json --stage <active-skill-name> --reason "Concrete failing gate, attempted repair and remaining blocker"
```

Stop after recording the blocked result and actual stage activity. A pending process/agent must be reconciled or stopped through its supported interface before treating that stage as quiescent; a blocked manifest alone does not stop runtime work. A new explicit resume can reattempt after inspecting changed evidence; do not automatically resume forever on an unchanged blocker.

## Resume and invalidation

First read the run manifest, source artifacts and current workspace. Inspect known native activity. If the manifest says a stage is running, the helper deliberately refuses reconciliation: the master must join, inspect or stop that exact run's work before completing/failing it. Do not clear running state just because the conversation resumed, and do not reset unrelated agent state.

Then run:

```bash
python3 <skill-dir>/scripts/stage_gate.py reconcile <run>/pipeline.json
```

This checks completed-stage fingerprints and invalidates the earliest stale stage plus all successors while preserving files. If an input is missing, recover it or report the blocker; do not fabricate its prior contents. Revalidate semantics and actual implementation evidence before reusing completed stages; fingerprints alone cannot prove a workspace is still correct. If semantic evidence is stale without file changes, invalidate the responsible stage explicitly with `python3 <skill-dir>/scripts/stage_gate.py invalidate <run>/pipeline.json --stage <skill-name> --reason "Concrete stale semantic evidence"`. This requires no active stage and archives affected receipts before resetting that stage and successors. Revalidate through a new audited attempt rather than claiming the old receipt proves current correctness.

When upstream changes invalidate implementation, preserve and inspect existing edits. Complete new upstream stages sequentially, then let the executor reconcile actual tasks/ownership/checks with the new plan/team before dispatch. Do not auto-revert user changes, blindly rerun writes, or delete old bundles. Preserve old receipts in audit history; keep each attempt's artifacts distinct.

A resume never overlaps a prior live stage. If all receipts remain valid and implementation proof is current, report completion without rerunning the chain. If stage 2 is blocked but stage 1 remains valid, resume from stage 2 only.
