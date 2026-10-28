#!/usr/bin/env python3
"""Deterministic manifest gate for the gexec stages."""
import argparse
import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path

STAGES = ["critical-path-planner", "backlog-team-designer", "native-plan-executor"]
SCHEMA_VERSION = 1


def fingerprint(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest()}


def _inputs(state, index):
    plan = fingerprint(state["plan"]["path"])
    if plan != state["plan"]:
        raise ValueError("plan changed; reconcile the manifest before continuing")
    result = [plan]
    for name in STAGES[:index]:
        record = state["stages"][name]
        if record["status"] != "completed":
            raise ValueError(f"predecessor {name} is not completed")
        for output in record["output_fingerprints"]:
            current = fingerprint(output["path"])
            if current != output:
                raise ValueError(f"predecessor output changed: {output['path']}")
            result.append(current)
    return result


def _check_inputs(state, record, index):
    current = _inputs(state, index)
    if current != record["input_fingerprints"]:
        raise ValueError("stage inputs changed; reconcile the manifest before continuing")


def init(plan_path):
    plan = fingerprint(plan_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "plan": plan,
        "active_stage": None,
        "stages": {
            name: {"status": "pending", "input_fingerprints": [], "output_fingerprints": [], "evidence": None}
            for name in STAGES
        },
        "history": [],
    }


def start(state, stage):
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if state.get("active_stage") is not None:
        raise ValueError(f"stage {state['active_stage']} is still running; reconcile runtime before proceeding")
    record = state["stages"][stage]
    if record["status"] not in ("pending", "blocked"):
        raise ValueError(f"stage {stage} is {record['status']}")
    index = STAGES.index(stage)
    inputs = _inputs(state, index)
    record.update(status="running", input_fingerprints=inputs, output_fingerprints=[], evidence=None)
    state["active_stage"] = stage
    return state


def finish(state, stage, outputs, evidence):
    if state.get("active_stage") != stage or state["stages"].get(stage, {}).get("status") != "running":
        raise ValueError(f"stage {stage} is not the active running stage")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("evidence must be nonempty text")
    index = STAGES.index(stage)
    _check_inputs(state, state["stages"][stage], index)
    if not outputs:
        raise ValueError("at least one output file is required")
    output_fingerprints = []
    input_paths = {item["path"] for item in state["stages"][stage]["input_fingerprints"]}
    for output in outputs:
        current = fingerprint(output)
        if current["path"] in input_paths:
            raise ValueError(f"output cannot be an input file: {current['path']}")
        if current not in output_fingerprints:
            output_fingerprints.append(current)
    record = state["stages"][stage]
    record.update(status="completed", output_fingerprints=output_fingerprints, evidence=evidence.strip())
    state["active_stage"] = None
    return state


def fail(state, stage, reason):
    if state.get("active_stage") != stage or state["stages"].get(stage, {}).get("status") != "running":
        raise ValueError(f"stage {stage} is not the active running stage")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be nonempty text")
    record = state["stages"][stage]
    record.update(status="blocked", output_fingerprints=[], evidence=reason.strip())
    state["history"].append({"stage": stage, "event": "blocked", "reason": reason.strip()})
    state["active_stage"] = None
    return state


def invalidate(state, stage, reason):
    if state.get("active_stage") is not None:
        raise ValueError(f"stage {state['active_stage']} is still running; cannot invalidate")
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason must be nonempty text")
    index = STAGES.index(stage)
    records = {name: copy.deepcopy(state["stages"][name]) for name in STAGES[index:]}
    state["history"].append({"event": "invalidated", "stage": stage, "reason": reason.strip(), "records": records})
    for name in STAGES[index:]:
        state["stages"][name].update(status="pending", input_fingerprints=[], output_fingerprints=[], evidence=None)
    return stage


def reconcile(state):
    if state.get("active_stage") is not None:
        raise ValueError(f"stage {state['active_stage']} is still running; runtime reconciliation is required")
    changed_plan = fingerprint(state["plan"]["path"])
    invalid_index = None
    for index, name in enumerate(STAGES):
        record = state["stages"][name]
        if record["status"] != "completed":
            continue
        try:
            expected_inputs = [changed_plan]
            for predecessor in STAGES[:index]:
                for output in state["stages"][predecessor]["output_fingerprints"]:
                    expected_inputs.append(fingerprint(output["path"]))
            inputs_valid = expected_inputs == record["input_fingerprints"]
            outputs_valid = all(fingerprint(item["path"]) == item for item in record["output_fingerprints"])
        except (ValueError, OSError):
            inputs_valid = outputs_valid = False
        if not inputs_valid or not outputs_valid:
            invalid_index = index
            break
    if changed_plan != state["plan"]:
        invalid_index = 0 if invalid_index is None else min(0, invalid_index)
    if invalid_index is None:
        state["plan"] = changed_plan
        return None
    state["plan"] = changed_plan
    return invalidate(state, STAGES[invalid_index], "fingerprint mismatch")


def _read(path):
    try:
        state = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read manifest: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != SCHEMA_VERSION or not isinstance(state.get("stages"), dict) or set(state["stages"]) != set(STAGES):
        raise ValueError("unsupported or malformed manifest")
    return state


def _write(path, state, refuse_existing=False):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise ValueError(f"manifest already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(state, stream, indent=2, sort_keys=True)
            stream.write("\n")
        if refuse_existing and path.exists():
            raise ValueError(f"manifest already exists: {path}")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init"); p.add_argument("manifest"); p.add_argument("--plan", required=True)
    p = sub.add_parser("start"); p.add_argument("manifest"); p.add_argument("--stage", required=True)
    p = sub.add_parser("finish"); p.add_argument("manifest"); p.add_argument("--stage", required=True); p.add_argument("--outputs", nargs="+", required=True); p.add_argument("--evidence", required=True)
    p = sub.add_parser("fail"); p.add_argument("manifest"); p.add_argument("--stage", required=True); p.add_argument("--reason", required=True)
    p = sub.add_parser("invalidate"); p.add_argument("manifest"); p.add_argument("--stage", required=True); p.add_argument("--reason", required=True)
    p = sub.add_parser("reconcile"); p.add_argument("manifest")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            state = init(args.plan)
            _write(args.manifest, state, refuse_existing=True)
            return 0
        state = _read(args.manifest)
        if args.command == "start": start(state, args.stage)
        elif args.command == "finish": finish(state, args.stage, args.outputs, args.evidence)
        elif args.command == "fail": fail(state, args.stage, args.reason)
        elif args.command == "invalidate": invalidate(state, args.stage, args.reason)
        else:
            result = reconcile(state)
            print(result or "")
        _write(args.manifest, state)
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
