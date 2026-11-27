"""Lossless file review, compact command evidence, and single-copy preparation context.

Only model-facing projections change. The original command receipts, source
artifacts, proposal digest, authorization and independent checks are untouched.
"""
from __future__ import annotations
from .policy import digest
from .scope_compiler import compact_contract

def preparation_context(profile,tasks,team,inventory):
    contract=compact_contract(profile,tasks,team)
    # Keep one exact check catalogue; no duplicate executable scripts.
    contract.pop("checks_by_index")
    return {"compiled_contract":contract,"checks":profile["checks"],
            "paths":profile["paths"],"write_paths":profile.get("write_paths",profile["paths"]),
            "inventory":inventory,"wheels":sorted(profile["wheels"]),
            "capacity":profile["capacity"],
            "tasks":[{k:t[k] for k in ("id","source","outcome","verification","depends_on","write_scope") if k in t}
                     for t in tasks["tasks"]],
            "extension_schema":{"scopes":{"task ID":{"reads":["exact relative file path"],
                                                     "writes":["exact relative file path"],"check_indices":[0]}}}}

def compact_receipts_for_master(receipts,catalog):
    result=[]
    for receipt in receipts:
        argv=receipt.get("argv",[])
        r={k:receipt[k] for k in ("exit_code","timeout","output_sha256","output_bytes","truncated","elapsed_ms") if k in receipt}
        r["argv_sha256"]=digest(argv)
        if argv in catalog:
            r["check_index"]=catalog.index(argv)
            r["kind"]="approved_check"
        elif argv[:3]==["python","-m","pip"]:
            r["kind"]="offline_install"
            r["wheel"]=argv[-1] if argv else None
        else:
            r["kind"]="other_sandbox_operation"
            # Never duplicate embedded Python source or file contents in the
            # context; the complete original argv remains in the audit journal.
            r["command_prefix"]=argv[:2]
        result.append(r)
    return result

def proposal_for_master(proposal,catalog):
    if proposal is None:return None
    return {**proposal,"commands":compact_receipts_for_master(proposal.get("commands",[]),catalog)}

def verification_for_master(result,catalog):
    r=dict(result)
    if "checks" in r:r["checks"]=compact_receipts_for_master(r["checks"],catalog)
    if isinstance(r.get("verification"),dict):
        r["verification"]=verification_for_master(r["verification"],catalog)
    return r
