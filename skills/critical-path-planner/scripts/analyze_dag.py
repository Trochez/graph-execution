"""Validate a finish-to-start DAG and calculate resource-unconstrained CPM."""
import argparse
import json
import math
import sys
from collections import deque
from pathlib import Path


def analyze(data):
    if not isinstance(data, dict) or not isinstance(data.get('tasks'), list) or not data['tasks']:
        raise ValueError('Expected an object with a nonempty tasks list')
    unit = data.get('unit')
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError('A nonempty duration unit is required')
    tasks = {}
    for task in data['tasks']:
        if not isinstance(task, dict):
            raise ValueError('Every task must be an object')
        task_id = task.get('id')
        duration = task.get('duration')
        deps = task.get('depends_on', [])
        if not isinstance(task_id, str) or not task_id.strip() or task_id in tasks:
            raise ValueError(f'Invalid or duplicate task ID: {task_id!r}')
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration < 0:
            raise ValueError(f'{task_id}: duration must be finite and nonnegative')
        if not isinstance(deps, list) or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise ValueError(f'{task_id}: depends_on must contain unique string IDs')
        tasks[task_id] = {'duration': duration, 'deps': deps}
    successors = {k: [] for k in tasks}
    remaining = {k: len(t['deps']) for k, t in tasks.items()}
    for key, task in tasks.items():
        for dep in task['deps']:
            if dep not in tasks:
                raise ValueError(f'{key}: unknown dependency {dep}')
            successors[dep].append(key)
    ready = [k for k in tasks if remaining[k] == 0]
    order, waves, timing = [], [], {}
    while ready:
        waves.append(ready)
        following = []
        for key in ready:
            order.append(key)
            start = max((timing[d]['earliest_finish'] for d in tasks[key]['deps']), default=0)
            timing[key] = {'earliest_start': start, 'earliest_finish': start + tasks[key]['duration']}
            for nxt in successors[key]:
                remaining[nxt] -= 1
                if remaining[nxt] == 0:
                    following.append(nxt)
        ready = following
    if len(order) != len(tasks):
        blocked = [k for k in tasks if remaining[k] > 0]
        raise ValueError(f'Dependency cycle; cyclic or downstream-blocked tasks: {blocked}')
    finish = max(t['earliest_finish'] for t in timing.values())
    if not math.isfinite(finish):
        raise ValueError('Cumulative duration overflow')
    for key in reversed(order):
        end = min((timing[n]['latest_start'] for n in successors[key]), default=finish)
        start = end - tasks[key]['duration']
        slack = start - timing[key]['earliest_start']
        critical = math.isclose(slack, 0, abs_tol=1e-9)
        timing[key].update(latest_start=start, latest_finish=end, **{'float': 0 if critical else slack}, critical=critical)
    edges = [[d, k] for k in tasks for d in tasks[k]['deps']]
    critical_edges = [[a, b] for a, b in edges if timing[a]['critical'] and timing[b]['critical']
                      and math.isclose(timing[a]['earliest_finish'], timing[b]['earliest_start'], rel_tol=0, abs_tol=1e-9)]
    critical_next = {k: [] for k in tasks}
    for a, b in critical_edges:
        critical_next[a].append(b)
    stack = deque(([k] for k in reversed(order) if not tasks[k]['deps'] and timing[k]['critical']))
    paths = []
    while stack and len(paths) < 101:
        path = stack.pop()
        last = path[-1]
        if not successors[last] and timing[last]['critical']:
            paths.append(path)
        else:
            stack.extend(path + [n] for n in reversed(critical_next[last]))
    return {'unit': unit, 'duration': finish, 'tasks': timing, 'edges': edges,
            'critical_edges': critical_edges, 'critical_paths': paths[:100],
            'critical_paths_truncated': len(paths) > 100, 'waves': waves,
            'scope': 'Dependency-only lower bound; unlimited resources, finish-to-start edges'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='Task JSON file')
    args = parser.parse_args()
    try:
        result = analyze(json.loads(args.input.read_text()))
        print(json.dumps(result, indent=2, allow_nan=False))
    except (ValueError, OSError, OverflowError) as exc:
        print(f'Invalid task graph: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
