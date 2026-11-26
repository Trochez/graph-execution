"""Opt-in local qualification barriers; external harness owns the actual interruption."""
import json,os,time
from pathlib import Path
from .cli import private_json

def barrier(kind,run_id,facts):
    raw=os.environ.get("GEXEC_QUALIFICATION_FAULT_CONTROL")
    if not raw:return
    root=Path(raw).resolve(strict=True)
    # The harness supplies an exclusive private directory and expected run identity.
    if not root.is_dir() or root.stat().st_mode&0o077:raise PermissionError("fault control directory must be private")
    if not run_id.startswith("gexec-"):raise ValueError("invalid fault run")
    marker=root/(kind+".json")
    try:private_json(marker,{"run_id":run_id,**facts})
    except FileExistsError:return
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        if (root/(kind+".released")).is_file():return
        time.sleep(.1)
    raise TimeoutError("qualification fault barrier not released")
