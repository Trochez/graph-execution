# Graph model and team definition contract

## Inputs and output bundle

Use a user-specified destination or a new `<backlog-stem>-team/` sibling directory. If occupied, choose a fresh numbered suffix. Preserve the original backlog. Write:

- `team-definition.md`: recommendation, evidence, diagrams, membership, task assignments, capacity comparison and handoffs.
- `task-graph.json`: normalized tasks, explicit/inferred relationships and source references.
- `graph-analysis.json`: helper output, separating technical edges and candidate communities.
- `team-definition.json`: structured recommended team and task/cluster/agent mappings, including constraints and alternatives.

A blocked input gets a diagnostic report with missing evidence and affected IDs, not a fabricated launch-ready structure. A dependency cycle requires clarification or a documented proposed repair; preserve original edges and do not claim feasibility until resolved.

## Graph normalization

Retain task fields such as source reference, outcome, verification, duration/unit, effort, estimate confidence/range, required capabilities, write scopes, gates, and existing ownership. Distinguish user requirements from provisional previous assignments. Do not replace explicit owners without identifying the proposed change. Unknown duration is not zero. External wait consumes elapsed time but may not occupy an agent.

Minimal helper input (additional task fields pass through the artifact as context):

```json
{
  "tasks": [
    {"id": "T1", "depends_on": []},
    {"id": "T2", "depends_on": ["T1"]},
    {"id": "T3", "depends_on": []}
  ],
  "couplings": [
    {"a": "T1", "b": "T2", "strength": 3, "kind": "shared-write", "evidence": "Both edit the same contract file; ownership cannot yet be partitioned"},
    {"a": "T2", "b": "T3", "strength": 2, "kind": "shared-artifact", "evidence": "Both need repeated changes to the same interface"}
  ]
}
```

The dependency graph is directed and must be acyclic, with valid references. Affinity is undirected; a high-affinity edge does not create a new prerequisite. The helper contributes strength 1 for dependency pairs. Explicit strengths use this transparent default scale:

| Strength | Meaning | Evidence |
|---|---|---|
| 1 | Weak relationship | One-way handoff or broad domain affinity |
| 2 | Moderate coupling | Repeated shared artifact/contract coordination |
| 3 | Strong ownership coupling | Shared mutable files/resource with no established safe partition |

Specialist labels alone do not justify grouping across stronger ownership boundaries. Each explicit coupling needs its kind, source/evidence and whether inferred. Avoid pairwise edges merely because tasks share a broad keyword. For repeated writes, enumerate relevant shared scopes; read-only shared use is not a write conflict. Use maximum strength per pair, not summed duplicate evidence.

Default root threshold is 2; subcluster threshold is 3. Connected components at the root threshold form candidate clusters; a higher threshold produces candidate subclusters inside a root. A proper split is retained only when it contains a non-singleton child; singleton-only nesting is omitted. Isolated tasks remain visible. Deterministic ordering supports reproducible comparisons. No hierarchy depth is compulsory.

This heuristic may merge many tasks through a chain of moderate edges; inspect large components for meaningful boundaries. Test one plausible alternate threshold/grouping when inferred edges near a threshold would change staffing. Keep genuinely strong shared-write constraints intact. Any manual regrouping must be recorded as a proposed membership change with evidence; retain the raw helper result. Distinguish robustness from graph aesthetics.

The helper only validates and proposes task communities; it does not infer input evidence, choose roles, schedule resources or find a globally optimal organization. It has no dependency on Graphify or a clustering package. Run `python3 <skill-dir>/scripts/test_analyze_team_graph.py` to verify its invariants.

## Team structure and staffing

Use available role identifiers for executable roles; domain specialties can be responsibilities within an existing role. When runtime availability cannot be established, mark role mapping provisional. `worker` is reserved for an active Team runtime; ordinary implementation can map to `executor`. Do not assume a nested reporting diagram grants recursive spawning permissions.

For each proposed agent record ID, runnable role/capabilities, responsibilities, task IDs, primary cluster, availability phases, write ownership, reporting/escalation route, handoff outputs, and completion proof. Cross-cutting reviewers can serve multiple clusters sequentially while remaining one agent. Every task has exactly one accountable execution owner; collaborators and reviewers are separate fields.

Count total distinct agents over the run and peak concurrent agents separately. Include the overall coordinator and any extra leads/reviewers. If a coordinator or lead also implements, reserve that time and do not overlap assignments. A lead can be a responsibility carried by an existing agent; state whether it adds headcount. Root and child cluster membership is nested task grouping, not duplicate staffing. Prefer one accountable cluster owner with specialist responsibilities to unnecessary inter-cluster handoffs.

Compare flat, clustered, and an adjacent useful capacity/structure (explain if constraints eliminate an option). State total/peak headcount, productive effort, elapsed completion estimate, coordination/review overhead, handoffs, idle periods, and risk. Provide a task-to-agent schedule sufficient to check dependencies, required skills, shared resources and non-overlap. Release or reassign idle capacity by phase. Respect review independence where specified.

Use a transparent ready-task priority heuristic (critical/low-float work first when reliable estimates exist) and explain resource-induced delays. Community membership does not require concurrent execution. A critical-path duration is a dependency lower bound, not the staffed schedule duration. If reliable estimates are absent, provide ranges or relative comparisons with provisional capacity; do not claim a numerical optimum.

Recommend the smallest useful structure near the speed/cost tradeoff. Show what the next agent/lead buys and costs. Coordination estimates must be visible, preferably ranges when uncertain. If alternatives are indistinguishable under uncertainty, say so and favor the simpler structure. A single agent may be the recommendation for a serial backlog. Strongly coupled work may remain one cluster with no subclusters. Do not invent a monetary cost without rates.

## Required human report

Include:
1. Source, input readiness, preserved requirements, inferred evidence, constraints and blockers.
2. Dependency/affinity graph rationale and clustering settings, resulting clusters and optional subclusters, all task IDs, and cross-cluster edges/contracts. Provide a Mermaid task graph using cluster subgraphs plus a separate agent coordination diagram (text tables can supplement large diagrams).
3. Flat/clustered/adjacent-capacity comparison and selected structure with marginal tradeoff and sensitivity findings.
4. Agent roster, total/peak size, role mapping, phase plan and complete task-to-leaf-cluster-to-owner table. Account for coordinator/leads explicitly.
5. Resource-feasible schedule, shared-write reservations, integration/review gates, cross-cluster handoff artifacts and escalation route.
6. Uncertainty, unresolved decisions, runtime fit and execution handoff checklist. No automatic launch.

## Structured team artifact

Use an object with `source`, `constraints`, `assumptions`, `graph_analysis`, `clusters`, `agents`, `task_assignments`, `schedule`, `staffing`, `alternatives`, and `open_questions`. Task assignments contain `task_id`, `leaf_cluster_id`, `owner_agent_id`, optional collaborators/reviewers. Agent records include `id`, `role`, responsibilities, reporting route and availability. `staffing` states `total_distinct_agents`, `peak_concurrent_agents`, coordinator/lead counts and whether roles share agents. Schedule records identify agent, task/activity, start/end and shared resources; units and estimates are explicit.

Every task must belong to exactly one leaf cluster and have one execution owner. Parent summaries repeat membership only for nesting, not additional assignment. Verify child partitions cover their parent without overlap, references resolve, all agents exist, task schedules honor original prerequisites, and shared writes/agent activities do not overlap. Verify no unapproved changes to fixed assignments, source tasks or runtime state occurred. Estimates and planning proofs do not establish future implementation correctness.
