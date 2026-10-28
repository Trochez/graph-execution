# Backlog and critical-path contract

## Output bundle

Use the user's destination if specified; otherwise create `<plan-stem>-execution/` beside the input plan (choose a fresh numbered suffix when occupied):

- `backlog.md`: human-readable planning report, task cards, dependency diagram, critical paths and parallel task branches.
- `tasks.json`: task records and assumptions, authoritative for calculation.
- `dag-analysis.json`: helper output for the unconstrained dependency schedule.

For an empty/non-actionable plan or unresolved dependency cycle, produce a concise blocked report instead of claiming an executable backlog. Retain evidence and open questions. Do not calculate a fictional completion date.

## Task data

Use a single duration unit, preferably performer-hours; distinguish elapsed external wait time from effort. Calculator durations are elapsed task estimates under the stated execution assumptions, not a promise. Label supplied versus inferred durations; add range/confidence and an estimation basis. If only relative units are defensible, use those consistently and avoid dates. If waits matter, model them as explicit gate tasks with zero performer effort and estimated elapsed duration, or leave completion conditional on an unknown gate.

```json
{
  "unit": "hours",
  "assumptions": ["Durations are rough elapsed estimates under the stated execution assumptions."],
  "tasks": [
    {
      "id": "T01",
      "title": "Publish the request/response contract",
      "source": "plan.md#api-contract",
      "outcome": "Backend and client can implement against the same versioned contract",
      "inputs": ["Source requirements"],
      "outputs": ["Contract artifact and representative payloads"],
      "depends_on": [],
      "dependency_reasons": {},
      "duration": 2,
      "effort": 2,
      "estimate": {"origin": "inferred", "range": [1, 3], "confidence": "medium", "basis": "One bounded interface"},
      "write_scope": ["shared API contract file; resolve exact path during grounding"],
      "verification": "Both consumer expectations validated against representative payloads",
      "handoff": "Contract version, location and verification evidence",
      "risks": []
    }
  ]
}
```

Every leaf task needs these concepts; use exact paths when discoverable and label provisional scopes. `depends_on` contains task IDs only. The helper consumes `id`, `duration`, `depends_on`, and `unit`; other fields preserve execution context. Milestones may have zero duration. Separate non-leaf summaries from `tasks` to avoid double counting.

For dependencies distinguish:
- Artifact dependency: explain which predecessor output is required.
- External gate: responsible external party if known, unblock condition and known/unknown wait.
- Resource restriction: shared file or environment; keep it separate from the technical DAG unless the work itself requires ordering.

## Human report

Include:

1. Source, scope, constraints, estimation units, assumptions and blockers.
2. Requirement-to-task coverage table (including verification, integration and release requirements present in source).
3. Task index and task cards with the fields above. Tasks should be assignable without needing the original conversation.
4. Complete Mermaid dependency DAG with task IDs, durations, forks and joins. Mark critical nodes/edges; include a text fallback for large diagrams. Avoid fabricating a single chain when tied critical paths exist.
5. Critical path(s), unconstrained lower-bound makespan, ES/EF/LS/LF and total float per task, plus near-critical branches and sensitivity to uncertain estimates. The helper's `latest_finish` shares one project finish across disconnected endpoints.
6. Parallel-task branch table covering every task: start prerequisite, fork, branch work, join, write scope, and handoff artifacts. Include topological readiness waves and identify shared-file or environment conflicts without assigning execution capacity.
7. Backlog handoff checklist and unresolved decisions. Planning ends here.

## Calculator semantics

`python3 <skill-dir>/scripts/analyze_dag.py tasks.json` prints JSON to stdout; errors go to stderr with exit 2. It checks nonempty tasks, unique IDs, finite nonnegative durations, dependency references and cycles. It does not verify source coverage, resource feasibility, estimation credibility or permissions.

The dependency calculation assumes finish-to-start edges, no lags and unlimited resources. Forward pass: ES=max predecessor EF, EF=ES+duration. Backward pass: LF=min successor LS, using common project finish for terminal tasks; LS=LF-duration. Float=LS-ES. Multiple starts/finishes are supported. Critical paths follow zero-float nodes and time-tight edges. At most 100 paths are emitted, with truncation flagged; all critical edges are retained. No critical-path count is claimed when enumeration is truncated.
