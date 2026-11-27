"""Safe classifications only: never return raw provider logs or exception payloads."""
import argparse
import json
import re
from pathlib import Path

PATTERNS={
    "startup_syntax":r"SyntaxError|was never closed|IndentationError",
    "startup_import":r"ImportError|ModuleNotFoundError|failed to import|could not import",
    "request_budget":r"UsageLimitExceeded|request.limit.{0,60}(?:exceeded|reached)|exceed.{0,40}request.limit|would exceed the request_limit",
    "context_overflow":r"context_length_exceeded|context window|maximum context length|too many input tokens",
    "provider_rate_limit":r"RateLimitError|rate_limit_exceeded|HTTP[/\s\d.]+429|status_code[=: ]+429",
    "provider_auth":r"AuthenticationError|PermissionDeniedError|invalid_api_key|status_code[=: ]+(?:401|403)",
    "provider_timeout":r"APITimeoutError|ReadTimeout|ConnectTimeout",
    "provider_connection":r"APIConnectionError|ConnectError",
    "provider_error":r"ModelHTTPError|APIStatusError|InternalServerError|BadRequestError|UnexpectedModelBehavior",
    "tool_validation":r"ToolRetryError|ValidationError|ToolError|ModelRetry",
    "temporal_failure":r"WorkflowUpdateFailedError|WorkflowFailureError|ActivityError|RPCError|workflow execution not found",
    "process_interrupt":r"KeyboardInterrupt|CancelledError|SIGTERM",
}

def classify(log: str) -> dict:
    # Signals, not a proven root cause: logs may include model text.
    found=[kind for kind,pattern in PATTERNS.items() if re.search(pattern,log,re.IGNORECASE)]
    return {"signals":found or ["unclassified"],"traceback_present":"Traceback (most recent call last)" in log}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path(".."))
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument("--workflow-id")
    group.add_argument("--latest",action="store_true")
    a=p.parse_args()
    matches=[]
    for folder in sorted(a.root.glob("gexec-live-smoke-*")):
        receipt=folder/"receipt.json"
        if not receipt.is_file():
            # Earlier runner could fail before creating a receipt.
            bundle=folder/"bundle.json"
            if not bundle.is_file():continue
            try:r={"workflow_id":json.loads(bundle.read_text())["spec"]["workflow_id"],"receipt_missing":True}
            except (OSError,ValueError,KeyError,TypeError):continue
        else:
            try:r=json.loads(receipt.read_text())
            except (OSError,ValueError):continue
        if a.latest or r.get("workflow_id")==a.workflow_id:matches.append((folder,r))
    if a.latest and matches:
        matches=[max(matches,key=lambda item:item[0].stat().st_mtime)]
    if len(matches)!=1:
        print(json.dumps({"diagnosis":"receipt_not_unique","matches":len(matches)}));return 2
    folder,r=matches[0]
    log=folder/"pax-local.log"
    if not log.is_file():
        print(json.dumps({"diagnosis":"log_missing","workflow_id":r.get("workflow_id"),"receipt_missing":r.get("receipt_missing",False),"stage":r.get("stage"),"error_type":r.get("error_type"),"rpc_status":r.get("rpc_status")}));return 2
    with log.open("rb") as f:
        f.seek(max(0,log.stat().st_size-2_000_000))
        diag=classify(f.read().decode("utf-8",errors="replace"))
    result={"workflow_id":r["workflow_id"],"pax_exit":r.get("pax_exit"),"tasks":r.get("tasks"),
            "peer_ack":r.get("peer_ack"),"final_checks":r.get("final_checks"),"diagnostics":diag,
            "stage":r.get("stage"),"error_type":r.get("error_type"),"rpc_status":r.get("rpc_status"),
            "receipt_missing":r.get("receipt_missing",False)}
    print(json.dumps(result,indent=2,sort_keys=True));return 0

if __name__=="__main__":
    raise SystemExit(main())
