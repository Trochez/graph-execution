"""Compare deterministic legacy CLI behavior with the immutable pre-migration revision.

No provider requests, native agent calls, or changes to installed skills.
The baseline files are read from Git objects, never the current branch.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BASELINE = "9ff68208acbbb822f30784f130e23c9db446dcfa"
ROOT = Path(__file__).resolve().parent.parent
HELPERS = {
    "dag": "skills/critical-path-planner/scripts/analyze_dag.py",
    "team": "skills/backlog-team-designer/scripts/analyze_team_graph.py",
    "model": "skills/native-plan-executor/scripts/model_policy.py",
    "gate": "skills/gexec/scripts/stage_gate.py",
}


def invoke(script, *args, expected_code=0):
    result = subprocess.run([sys.executable, str(script), *map(str, args)],
                            capture_output=True, text=True, timeout=20)
    if result.returncode != expected_code:
        raise AssertionError(f"{script.name}: expected {expected_code}, got {result.returncode}: {result.stderr}")
    return json.loads(result.stdout) if result.stdout.strip().startswith(("{", "[")) else result.stdout.strip()


def dump(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def exercise(scripts, root):
    tasks = root / "tasks.json"
    dump(tasks, {"unit": "hours", "tasks": [
        {"id": "A", "duration": 2, "depends_on": []},
        {"id": "B", "duration": 4, "depends_on": ["A"]},
        {"id": "C", "duration": 3, "depends_on": ["A"]},
        {"id": "D", "duration": 2, "depends_on": ["B", "C"]},
    ]})
    team = root / "team-input.json"
    dump(team, {"tasks": [{"id": "a"}, {"id": "b"},
                         {"id": "c", "depends_on": ["b"]}, {"id": "d"}],
                "couplings": [{"a": "a", "b": "b", "strength": 4, "kind": "shared-file", "evidence": "a/b"},
                              {"a": "c", "b": "d", "strength": 4, "kind": "shared-file", "evidence": "c/d"}]})
    policy = root / "model-policy.json"
    dump(policy, {"schema_version": 1, "model_id": "model-a",
                  "confirmed_on": "2025-12-15", "confirmed_month": "2025-12",
                  "selection_basis": "user preference", "confirmation_note": "I confirm model-a"})
    manifest = root / "pipeline.json"
    manifest.unlink(missing_ok=True)
    plan = root / "plan.md"
    plan.write_text("# Synthetic plan", encoding="utf-8")
    output = root / "backlog.json"
    output.write_text("synthetic artifact", encoding="utf-8")
    results = {
        "dag": invoke(scripts["dag"], tasks),
        "team": invoke(scripts["team"], team),
        "model_policy_seed": json.loads(policy.read_text()),
    }
    # Exercise the public Python functions for the deterministic monthly policy:
    # the original CLI must keep its exact invocation syntax independently.
    import importlib.util
    spec = importlib.util.spec_from_file_location("legacy_model_fixture", scripts["model"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    results["same_month"] = module.status(policy, {"model-a", "model-b"}, module.date(2025, 12, 20))
    results["new_month"] = module.status(policy, {"model-a", "model-b"}, module.date(2026, 1, 1))
    results["unavailable"] = module.status(policy, {"model-b"}, module.date(2025, 12, 20))
    assert json.loads(policy.read_text()) == results["model_policy_seed"]
    invoke(scripts["gate"], "init", manifest, "--plan", plan)
    invoke(scripts["gate"], "start", manifest, "--stage", "critical-path-planner")
    invoke(scripts["gate"], "finish", manifest, "--stage", "critical-path-planner",
           "--outputs", output, "--evidence", "verified")
    results["manifest"] = json.loads(manifest.read_text())
    output.write_text("modified artifact", encoding="utf-8")
    results["reconcile"] = invoke(scripts["gate"], "reconcile", manifest)
    results["reconciled_manifest"] = json.loads(manifest.read_text())
    return results


def main():
    with tempfile.TemporaryDirectory(prefix="gexec-baseline-") as tmp:
        root = Path(tmp)
        baseline = {}
        for key, path in HELPERS.items():
            content = subprocess.check_output(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT)
            baseline[key] = root / Path(path).name
            baseline[key].write_bytes(content)
        expected = exercise(baseline, root)
        observed = exercise({key: ROOT / path for key, path in HELPERS.items()}, root)
        if observed != expected:
            changed = sorted(key for key in expected if expected[key] != observed.get(key))
            raise AssertionError(f"Legacy compatibility regression: {changed}")
        print(json.dumps({"baseline": BASELINE, "probe": "PASS",
                          "compared": sorted(expected), "native_host_qualification": False}))


if __name__ == "__main__":
    main()
