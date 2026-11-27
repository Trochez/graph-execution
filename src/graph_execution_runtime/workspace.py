"""Master-controlled exact-path proposals and integration. Trusted local workspace only.

Workers never get filesystem mutation or shell tools. This is not an OS sandbox
against concurrent untrusted local processes. Refuse symlinks, special files,
scope escapes, stale bases, and oversize files. No automatic retry of effects.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path

from .scheduler import normalized

MAX_BYTES = 65536
ABSENT = "absent"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def target(root: Path, name: str) -> Path:
    normalized(name)
    root = root.resolve(strict=True)
    p = root
    for part in name.split("/"):
        p = p / part
        if p.is_symlink():
            raise ValueError("symlinks are not allowed")
    if not p.parent.is_dir():
        raise ValueError("parent directory must already exist")
    if p.exists() and (not p.is_file() or p.stat().st_nlink != 1):
        raise ValueError("not a single-link regular file")
    return p


def snapshot(root: Path, name: str) -> tuple[str, str | None]:
    p = target(root, name)
    if not p.exists():
        return ABSENT, None
    if p.stat().st_size > MAX_BYTES:
        raise ValueError("file exceeds candidate size limit")
    data = p.read_bytes()
    return sha(data), data.decode("utf-8")


def validate_proposal(root: Path, task: dict, edits: list[dict]) -> list[dict]:
    if not isinstance(edits, list) or len(edits) > 8:
        raise ValueError("too many edits")
    seen = set()
    total = 0
    for edit in edits:
        if set(edit) != {"path", "base", "content", "sha256"}:
            raise ValueError("invalid edit fields")
        path = edit["path"]
        if path in seen or path not in task["writes"]:
            raise ValueError("duplicate or out-of-scope edit")
        seen.add(path)
        encoded = edit["content"].encode("utf-8")
        total += len(encoded)
        if len(encoded) > MAX_BYTES or total > 196608 or sha(encoded) != edit["sha256"]:
            raise ValueError("edit size or digest mismatch")
        current, _ = snapshot(root, path)
        if current != edit["base"]:
            raise ValueError("base changed; reconciliation required")
    return sorted(edits, key=lambda e: e["path"])


def write_journal(path: Path, record: dict):
    # Exclusive creation ensures an uncertain prior effect cannot be retried.
    with path.open("x", encoding="utf-8") as f:
        json.dump(record, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())


def integrate(root: Path, journal: Path, task: dict, attempt: int, edits: list[dict]) -> dict:
    edits = validate_proposal(root, task, edits)
    journal.mkdir(mode=0o700, parents=True, exist_ok=True)
    # User chooses a private trusted journal directory outside the worktree.
    if journal.is_symlink() or not journal.is_dir():
        raise ValueError("unsafe journal directory")
    key = sha(f"{task['id']}:{attempt}".encode())
    intent = journal / (key + ".intent.json")
    receipt = journal / (key + ".done.json")
    facts = [{"path": e["path"], "base": e["base"], "sha256": e["sha256"]} for e in edits]
    write_journal(intent, {"task": task["id"], "attempt": attempt, "files": facts})
    for e in edits:
        p = target(root, e["path"])
        if snapshot(root, e["path"])[0] != e["base"]:
            raise ValueError("base changed after journal; inspect partial effects")
        mode = stat.S_IMODE(p.stat().st_mode) if p.exists() else 0o644
        fd, name = tempfile.mkstemp(dir=p.parent, prefix=".gexec-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(e["content"].encode("utf-8"))
                f.flush()
                os.fsync(f.fileno())
            os.chmod(name, mode)
            if snapshot(root, e["path"])[0] != e["base"]:
                raise ValueError("base changed before replacement")
            os.replace(name, p)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    if any(snapshot(root, e["path"])[0] != e["sha256"] for e in edits):
        raise ValueError("post-integration hash mismatch")
    write_journal(receipt, {"task": task["id"], "attempt": attempt, "files": facts})
    return {"applied": True, "files": facts, "journal_id": key}
