#!/usr/bin/env python3
"""Collect safe preflight evidence; this is not a host qualification test.

Run from a clean checkout, inside the intended Python environment.
No provider calls, credentials, model configuration, or services are modified.
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata as metadata
import json
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

SKILLS = ("critical-path-planner", "backlog-team-designer", "native-plan-executor", "gexec")
PACKAGES = ("pydantic", "pydantic-ai", "pydantic-ai-slim", "pydantic-graph",
            "pydantic-ai-pax", "pydantic-ai-harness", "temporalio")
BASELINE = "9ff68208acbbb822f30784f130e23c9db446dcfa"


def run(argv, cwd, timeout=120):
    try:
        result = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                                timeout=timeout, errors="replace")
        return {"exit_code": result.returncode,
                "stdout": result.stdout[-16000:], "stderr": result.stderr[-16000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"exit_code": None, "error_type": type(exc).__name__}


def version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def tcp_probe(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="New JSON evidence file; preferably outside the checkout.")
    parser.add_argument("--temporal-port", type=int, default=7233)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if not 1 <= args.temporal_port <= 65535:
        parser.error("invalid Temporal port")
    if args.output.exists():
        parser.error("output already exists; preserve prior evidence")
    head = run(["git", "rev-parse", "HEAD"], root)
    dirty = run(["git", "status", "--porcelain"], root)
    # Do not record dirty filenames, absolute executable paths or CLI config.
    report = {
        "schema_version": 1,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "platform": platform.system(), "python": platform.python_version(),
        "baseline_sha": BASELINE,
        "head": head.get("stdout", "").strip() if head["exit_code"] == 0 else None,
        "clean_checkout": dirty["exit_code"] == 0 and not dirty.get("stdout", "").strip(),
        "baseline_ancestor": run(["git", "merge-base", "--is-ancestor", BASELINE, "HEAD"], root)["exit_code"] == 0,
        "executables_present": {name: bool(shutil.which(name)) for name in
                                ("git", "pax", "codex", "cline", "temporal", "uv")},
        "package_versions": {name: version(name) for name in PACKAGES},
        "temporal_local_tcp_open": tcp_probe(args.temporal_port),
        "legacy_tests": {},
        "live_host_qualification": "NOT_RUN",
        "decision": "NO_GO_UNTIL_LIVE_SPIKES",
    }
    for skill in SKILLS:
        result = run([sys.executable, "-m", "unittest", "discover", "-s",
                      str(root / "skills" / skill / "scripts"), "-p", "test_*.py", "-v"], root)
        # Test output may contain local paths; retain only process outcome in portable receipt.
        report["legacy_tests"][skill] = {"exit_code": result["exit_code"]}
        print(f"{skill}: {result['exit_code']}", file=sys.stderr)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))
    return 0 if (report["head"] and report["clean_checkout"] and report["baseline_ancestor"]
                 and all(x["exit_code"] == 0 for x in report["legacy_tests"].values())) else 2


if __name__ == "__main__":
    raise SystemExit(main())
