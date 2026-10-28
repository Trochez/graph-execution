#!/usr/bin/env python3
"""Small, local persistence helper for explicitly confirmed model selections."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import date


def default_config_path():
    codex_home = os.environ.get("CODEX_HOME")
    return Path(codex_home).expanduser() / "native-plan-executor/model-policy.json" if codex_home else Path.home() / ".codex/native-plan-executor/model-policy.json"


def _read_config(path, today=None):
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return None, "initial"
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, "invalid"
    if not _valid_selection(value):
        return None, "invalid"
    try:
        confirmed = date.fromisoformat(value["confirmed_on"])
        if (
            confirmed.isoformat() != value["confirmed_on"]
            or confirmed.strftime("%Y-%m") != value["confirmed_month"]
            or confirmed > (today or date.today())
        ):
            return None, "invalid"
    except (TypeError, ValueError):
        return None, "invalid"
    return value, None


def _valid_selection(value):
    return (
        isinstance(value, dict)
        and type(value.get("schema_version")) is int
        and value.get("schema_version") == 1
        and isinstance(value.get("model_id"), str)
        and bool(value["model_id"].strip())
        and isinstance(value.get("confirmed_on"), str)
        and isinstance(value.get("confirmed_month"), str)
        and isinstance(value.get("selection_basis"), str)
        and bool(value["selection_basis"].strip())
        and isinstance(value.get("confirmation_note"), str)
        and bool(value["confirmation_note"].strip())
    )


def _today(value):
    if value is None:
        return date.today()
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("--today must be an ISO date (YYYY-MM-DD)")
    return parsed


def _validate_available(available):
    if not available or any(not isinstance(model_id, str) or not model_id.strip() for model_id in available):
        raise ValueError("available inventory must contain nonblank model IDs")


def status(path, available, today):
    _validate_available(available)
    selection, error = _read_config(path, today)
    if error:
        return {"requires_confirmation": True, "reason": error, "selection": None}
    if selection["model_id"] not in available:
        reason = "unavailable"
    elif selection["confirmed_month"] != today.strftime("%Y-%m"):
        reason = "monthly_review"
    else:
        reason = "reuse"
    return {"requires_confirmation": reason != "reuse", "reason": reason, "selection": selection}


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def confirm(path, model, available, today, basis, note):
    _validate_available(available)
    if not isinstance(model, str) or not model.strip():
        raise ValueError("selected model ID must be nonblank")
    if not basis.strip() or not note.strip():
        raise ValueError("--basis and --confirmation must be nonempty")
    if model not in available:
        raise ValueError("selected model is not in the provided available inventory")
    existing, error = _read_config(path, today)
    if error == "invalid":
        raise ValueError("existing config is malformed or unsupported; refusing to overwrite")
    value = dict(existing or {})
    value.update({
        "schema_version": 1,
        "model_id": model,
        "confirmed_on": today.isoformat(),
        "confirmed_month": today.strftime("%Y-%m"),
        "selection_basis": basis.strip(),
        "confirmation_note": note.strip(),
    })
    _atomic_write(path, value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--config", type=Path, default=default_config_path())
    status_parser.add_argument("--today")
    status_parser.add_argument("--available", nargs="+", required=True, metavar="MODEL_ID")
    confirm_parser = subparsers.add_parser("confirm")
    confirm_parser.add_argument("--config", type=Path, default=default_config_path())
    confirm_parser.add_argument("--today")
    confirm_parser.add_argument("--model", required=True)
    confirm_parser.add_argument("--available", nargs="+", required=True, metavar="MODEL_ID")
    confirm_parser.add_argument("--confirmation", required=True)
    confirm_parser.add_argument("--basis", required=True)
    args = parser.parse_args(argv)
    try:
        today = _today(args.today)
        if args.command == "status":
            result = status(args.config, set(args.available), today)
        else:
            result = confirm(args.config, args.model, set(args.available), today, args.basis, args.confirmation)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
