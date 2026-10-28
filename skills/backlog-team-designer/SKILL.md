---
name: backlog-team-designer
description: Use when an existing task backlog needs a graph-based team definition with team size, roles, task clusters, subclusters, ownership, and an execution structure before agents are launched.
---

# Backlog Team Designer

Design an agent team from existing tasks, balancing completion time with agent effort, handoffs and coordination. Derive task communities first, then justify the agent structure. A cluster is an ownership/work boundary, not automatically an agent or supervisor.

## Intake and boundaries

Read the supplied backlog, governing instructions and relevant local contracts. Accept Markdown task lists or structured records, including `critical-path-planner`'s `tasks.json`; that skill is optional. Preserve source IDs, requirements and dependencies. Assign stable IDs when absent and record the mapping. For a high-level plan lacking assignable tasks, identify the missing decomposition and recommend a planning workflow rather than silently expanding scope.

Carry explicit role availability, concurrency caps, budget, deadline, review independence, estimates and runtime limitations into the design. Infer missing relationships and estimates from available evidence, mark them provisional, and ask only when a gap materially changes the recommendation. Unknown relationships are not proof of independence.

Read [the graph and team contract](references/team-contract.md) before constructing artifacts.

## Graph analysis

Keep three graphs distinct:
- Directed task dependencies determine readiness and prerequisite handoffs.
- Weighted, undirected task affinity captures shared artifacts, write ownership and tight coupling.
- Agent coordination topology defines who owns work, integrates results and resolves cross-cluster decisions.

Build normalized graph input, citing evidence for couplings. Shared-write coupling takes priority over specialist labels; assign specialist responsibilities inside a cluster when economical. Record cross-cluster resource conflicts even after clustering.

Run the deterministic candidate-community helper:

```bash
python3 <skill-dir>/scripts/analyze_team_graph.py <output-dir>/task-graph.json > <output-dir>/graph-analysis.json
```

Resolve `<skill-dir>` to this skill's installed directory. Inspect graph validity and the helper's limitations. Its thresholds propose communities; they do not optimize staffing. Use the contract to evaluate clustering sensitivity and alternatives. Resolve cycles or unknown prerequisites before claiming a feasible execution plan.

## Design the team

Compare a flat team with the candidate clustered structure and a useful adjacent capacity. Match staffing to ready work and available skills; schedule shared writes and reviews explicitly. Explain where adding an agent reduces completion time enough to justify effort and coordination. Recommend the smallest capacity near that tradeoff, respecting the supplied cap.

Subclusters and leads are optional. Add them only for useful independent work or a coordination boundary with a demonstrated benefit. Prefer a flat structure for small or tightly coupled work. Account for each agent's time across roles and phases; avoid counting one person multiple times or scheduling them on overlapping tasks.

Give every task one accountable execution owner. State integration, independent review when required, cross-cluster contracts and escalation ownership. Proposed agent hierarchy must fit the actual runtime's delegation/concurrency limits; task nesting need not become recursive agent spawning.

## Deliver and stop

Write the artifact bundle defined in the contract. Verify complete task coverage, preserved dependency direction, ownership, staffing arithmetic, capacity-safe schedules and source preservation. Report the recommended team, alternatives, graph evidence, uncertainty and artifact links.

This skill produces a team definition only. Do not launch agents, execute tasks, alter the source backlog, or mutate team/goal runtime state. A separate explicit execution request selects the implementation workflow.
