#!/usr/bin/env python3
"""Derive deterministic candidate task communities from explicit graph evidence."""

import argparse
import json
import math
import sys
from collections import deque


def _positive_number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite positive number")
    try:
        valid = math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite positive number")


def _nonempty_string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")


def _components(tasks, edges, threshold):
    adjacency = {task: set() for task in tasks}
    for edge in edges:
        if edge["weight"] >= threshold and edge["a"] in adjacency and edge["b"] in adjacency:
            adjacency[edge["a"]].add(edge["b"])
            adjacency[edge["b"]].add(edge["a"])
    remaining = set(tasks)
    components = []
    for task in sorted(tasks):
        if task not in remaining:
            continue
        remaining.remove(task)
        pending = [task]
        component = []
        while pending:
            current = pending.pop()
            component.append(current)
            for neighbor in sorted(adjacency[current]):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    pending.append(neighbor)
        components.append(sorted(component))
    return components


def analyze_graph(data, cluster_threshold=2, subcluster_threshold=3):
    """Validate a technical DAG, then threshold its undirected affinity graph.

    Dependency direction is preserved separately. Communities are heuristic
    candidates and make no claim about optimal staffing or team boundaries.
    """
    _positive_number(cluster_threshold, "cluster threshold")
    _positive_number(subcluster_threshold, "subcluster threshold")
    if subcluster_threshold <= cluster_threshold:
        raise ValueError("subcluster threshold must be greater than cluster threshold")
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("tasks must be a nonempty list")
    task_ids = set()
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"tasks[{index}] must be an object")
        task_id = task.get("id")
        _nonempty_string(task_id, f"tasks[{index}].id")
        if task_id in task_ids:
            raise ValueError(f"duplicate task id: {task_id}")
        task_ids.add(task_id)

    dependency_edges = []
    indegrees = {task: 0 for task in task_ids}
    successors = {task: [] for task in task_ids}
    for index, task in enumerate(tasks):
        dependencies = task.get("depends_on", [])
        if not isinstance(dependencies, list):
            raise ValueError(f"tasks[{index}].depends_on must be a list")
        seen = set()
        for dependency in dependencies:
            label = f"tasks[{index}].depends_on"
            _nonempty_string(dependency, label)
            if dependency not in task_ids:
                raise ValueError(f"{label} references unknown task: {dependency}")
            if dependency == task["id"]:
                raise ValueError(f"{label} contains a self dependency: {dependency}")
            if dependency in seen:
                raise ValueError(f"{label} contains duplicate dependency: {dependency}")
            seen.add(dependency)
            dependency_edges.append({"from": dependency, "to": task["id"]})
            successors[dependency].append(task["id"])
            indegrees[task["id"]] += 1
    ready = deque(task for task in sorted(task_ids) if indegrees[task] == 0)
    visited = 0
    while ready:
        task = ready.popleft()
        visited += 1
        for successor in successors[task]:
            indegrees[successor] -= 1
            if indegrees[successor] == 0:
                ready.append(successor)
    if visited != len(task_ids):
        raise ValueError("technical dependency graph contains a cycle")
    dependency_edges.sort(key=lambda edge: (edge["from"], edge["to"]))

    affinity = {}

    def add_affinity(a, b, weight, kind, evidence):
        pair = tuple(sorted((a, b)))
        edge = affinity.setdefault(pair, {"weight": weight, "kinds": set(), "evidence": set()})
        edge["weight"] = max(edge["weight"], weight)
        edge["kinds"].add(kind)
        edge["evidence"].add(evidence)

    for edge in dependency_edges:
        add_affinity(edge["from"], edge["to"], 1, "dependency", "predecessor output")
    couplings = data.get("couplings", [])
    if not isinstance(couplings, list):
        raise ValueError("couplings must be a list")
    for index, coupling in enumerate(couplings):
        label = f"couplings[{index}]"
        if not isinstance(coupling, dict):
            raise ValueError(f"{label} must be an object")
        for field in ("a", "b", "kind", "evidence"):
            _nonempty_string(coupling.get(field), f"{label}.{field}")
        for field in ("a", "b"):
            if coupling[field] not in task_ids:
                raise ValueError(f"{label}.{field} references unknown task: {coupling[field]}")
        if coupling["a"] == coupling["b"]:
            raise ValueError(f"{label} must not couple a task to itself")
        _positive_number(coupling.get("strength"), f"{label}.strength")
        add_affinity(coupling["a"], coupling["b"], coupling["strength"], coupling["kind"], coupling["evidence"])
    affinity_edges = [
        {"a": a, "b": b, "weight": edge["weight"], "kinds": sorted(edge["kinds"]),
         "evidence": sorted(edge["evidence"])}
        for (a, b), edge in sorted(affinity.items())
    ]

    clusters = []
    task_to_leaf = {}
    for index, component in enumerate(_components(task_ids, affinity_edges, cluster_threshold), 1):
        cluster_id = f"C{index:02d}"
        children = _components(component, affinity_edges, subcluster_threshold)
        subclusters = []
        if len(children) > 1 and any(len(child) > 1 for child in children):
            subclusters = [{"id": f"{cluster_id}.S{child_index:02d}", "tasks": child}
                           for child_index, child in enumerate(children, 1)]
        cluster = {"id": cluster_id, "tasks": component, "subclusters": subclusters}
        clusters.append(cluster)
        for leaf in subclusters or [cluster]:
            for task in leaf["tasks"]:
                task_to_leaf[task] = leaf["id"]

    return {
        "dependency_edges": dependency_edges,
        "affinity_edges": affinity_edges,
        "clusters": clusters,
        "task_to_leaf": dict(sorted(task_to_leaf.items())),
        "thresholds": {"cluster": cluster_threshold, "subcluster": subcluster_threshold},
        "limitations": [
            "Thresholded connected components are heuristic candidate task communities, not optimized teams or headcount.",
            "Results depend on supplied coupling evidence and thresholds; indirect links can join dissimilar tasks.",
            "Dependency direction is retained separately and does not imply organizational reporting or parallel execution.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="Path to input JSON")
    parser.add_argument("--cluster-threshold", type=float, default=2)
    parser.add_argument("--subcluster-threshold", type=float, default=3)
    args = parser.parse_args(argv)
    try:
        with open(args.input, encoding="utf-8") as source:
            data = json.load(source)
        result = analyze_graph(data, args.cluster_threshold, args.subcluster_threshold)
    except (OSError, UnicodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
