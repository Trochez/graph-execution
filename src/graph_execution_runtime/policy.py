"""Explicit local project authorization; generated plans may only narrow it."""
from __future__ import annotations
import hashlib
import json
import re
import stat
from pathlib import Path
from .scheduler import normalized

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def hash_file(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1024*1024),b""):h.update(b)
    return h.hexdigest()

def safe_path(path):
    normalized(path)
    if any(x.startswith(".") or x.lower() in ("credentials","secrets","id_rsa","id_ed25519") or x.lower().endswith((".pem",".key",".p12",".pfx")) for x in path.split("/")):
        raise ValueError("reserved or sensitive path")
    if not re.fullmatch(r"[A-Za-z0-9_./-]+",path):
        raise ValueError("unsupported path characters")
    return path

def within(path, prefixes):
    return any(path==p or path.startswith(p+"/") for p in prefixes)

def required_check_indices(profile,writes):
    """Operator-approved write-group checks, matched only to actual write paths."""
    return sorted({i for group,indices in profile.get("required_checks_by_write_group",{}).items()
                   if any(within(path,[group]) for path in writes) for i in indices})

def validate_required_checks(profile):
    rules=profile.get("required_checks_by_write_group",{})
    if not isinstance(rules,dict) or len(rules)>30:raise ValueError("invalid required check mapping")
    for group,indices in rules.items():
        if not within(safe_path(group),profile.get("write_paths",profile["paths"])):
            raise ValueError("required check group outside write policy")
        if not isinstance(indices,list) or not 1<=len(indices)<=4 or any(type(i)!=int or not 0<=i<len(profile["checks"]) for i in indices) or len(set(indices))!=len(indices):
            raise ValueError("invalid mandatory check indices")

def command(argv, allowed):
    if not isinstance(argv,list) or not 1<=len(argv)<=24 or any(type(x)!=str or not x or len(x)>2048 or "\x00" in x for x in argv):
        raise ValueError("invalid argv")
    # The process runs only inside the offline restricted container.
    if argv[0] not in allowed or argv[0] not in ("python","pytest"):
        raise PermissionError("command family not approved")
    # Dependency installation uses a separate broker. Python code can execute
    # inside the sandbox, but never receives host mounts or provider secrets.
    if argv[:3]==["python","-m","pip"] or argv[0]=="pip":
        raise PermissionError("use the offline install broker")
    return argv

def validate_profile(p, root, *, verify_wheels=True):
    fields={"schema","workspace","image","wheelhouse","wheels","paths","commands","checks","final_checks","capacity","timeout","acknowledge","model","base_url","approval","skill_root"}
    if not isinstance(p,dict) or not fields<=set(p) or set(p)-fields-{"oracle","oracle_files","write_paths","required_parallel_roots","require_independent_review","required_peer_handoff","required_checks_by_write_group"} or p["schema"]!=2 or p["acknowledge"]!="local-trusted-docker-offline":
        raise ValueError("invalid profile schema or approval")
    if Path(p["workspace"]).resolve()!=root.resolve():
        raise ValueError("profile belongs to another repository")
    if not re.fullmatch(r"[A-Za-z0-9./:_-]+@sha256:[0-9a-f]{64}",p["image"]):
        raise ValueError("immutable image reference required")
    for k in ("paths","commands","checks","final_checks"):
        if not isinstance(p[k],list) or not p[k]:raise ValueError("empty policy field "+k)
    if len(p["paths"])>30 or len(set(p["paths"]))!=len(p["paths"]):raise ValueError("path policy bounds")
    for path in p["paths"]:safe_path(path)
    if "write_paths" in p:
        if not isinstance(p["write_paths"],list) or any(not within(safe_path(x),p["paths"]) for x in p["write_paths"]):raise ValueError("invalid write policy")
    if "required_parallel_roots" in p:
        pair=p["required_parallel_roots"]
        from .scheduler import conflicts
        if not isinstance(pair,list) or len(pair)!=2 or any(not within(safe_path(x),p.get("write_paths",p["paths"])) for x in pair) or conflicts(*pair) or p["capacity"]<2:
            raise ValueError("invalid required parallel root policy")
    if "required_peer_handoff" in p and (type(p["required_peer_handoff"])!=bool or (p["required_peer_handoff"] and not p.get("required_parallel_roots"))):raise ValueError("invalid peer handoff policy")
    if "require_independent_review" in p and type(p["require_independent_review"])!=bool:raise ValueError("invalid review policy")
    from .config import validate_endpoint
    validate_endpoint(p["base_url"])
    if not p["model"].startswith("openai:") or not p["model"][7:].strip():raise ValueError("provider-qualified route required")
    if not Path(p["skill_root"]).is_absolute() or not (Path(p["skill_root"])/"skills/gexec/SKILL.md").is_file():raise ValueError("installed skill root required")
    if not Path(p["approval"]).is_absolute():raise ValueError("absolute approval path required")
    if not set(p["commands"])<= {"python","pytest"}:raise ValueError("unknown command family")
    for argv in p["checks"]+p["final_checks"]:command(argv,p["commands"])
    if len(p["checks"])>16 or len(p["final_checks"])>8:raise ValueError("verification command budget")
    validate_required_checks(p)
    if type(p["capacity"])!=int or not 1<=p["capacity"]<=3 or type(p["timeout"])!=int or not 60<=p["timeout"]<=1200:
        raise ValueError("run budget outside supported limits")
    wheelhouse=Path(p["wheelhouse"]).resolve(strict=True)
    if not wheelhouse.is_dir() or wheelhouse.is_relative_to(root.resolve()) or root.resolve().is_relative_to(wheelhouse):
        raise ValueError("wheelhouse must be separate from target")
    if not isinstance(p["wheels"],dict) or len(p["wheels"])>100:raise ValueError("invalid wheel inventory")
    for name,checksum in p["wheels"].items():
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl",name) or not re.fullmatch(r"[0-9a-f]{64}",checksum):
            raise ValueError("invalid wheel inventory record")
        f=wheelhouse/name
        if verify_wheels and (not f.is_file() or f.is_symlink() or hash_file(f)!=checksum):
            raise ValueError("wheel hash mismatch")
    if verify_wheels and {f.name for f in wheelhouse.iterdir()}!=set(p["wheels"]):
        raise ValueError("wheelhouse must contain only approved wheels")
    if ("oracle" in p)!=("oracle_files" in p):raise ValueError("oracle path and inventory must be paired")
    if "oracle" in p:
        oracle=Path(p["oracle"]).resolve(strict=True)
        if not oracle.is_dir() or oracle.is_relative_to(root.resolve()) or root.resolve().is_relative_to(oracle):raise ValueError("oracle must be outside project")
        files=p["oracle_files"]
        if not isinstance(files,dict) or not files or set(files)!={f.name for f in oracle.iterdir()}:raise ValueError("oracle inventory mismatch")
        for name,checksum in files.items():
            safe_path(name)
            f=oracle/name
            if "/" in name or not f.is_file() or f.is_symlink() or hash_file(f)!=checksum:raise ValueError("oracle hash mismatch")
    return p

def load_profile(path, root):
    path=Path(path).resolve(strict=True)
    if path.is_relative_to(root.resolve()) or stat.S_IMODE(path.stat().st_mode)&0o077:
        raise PermissionError("profile must be private and outside project")
    return validate_profile(json.loads(path.read_text()),root)

def profile_path(root):
    return Path.home()/".config/graph-execution/projects"/(hashlib.sha256(str(root.resolve()).encode()).hexdigest()+".json")

def compile_settings(profile, tasks, team, extension):
    if not isinstance(extension,dict) or set(extension)!={"master","roles","parents","scopes"}:
        raise ValueError("execution extension contract")
    rows=tasks["tasks"];ids={t["id"] for t in rows};agents={a["id"] for a in team["agents"]}
    if not 1<=len(rows)<=16 or len(rows)!=len(ids) or set(extension["scopes"])!=ids or set(extension["roles"])!=agents or set(extension["parents"])!=agents:
        raise ValueError("scope or role coverage")
    scopes={}
    per_task=min(12,60//len(rows))
    for t in rows:
        k=t["id"];s=extension["scopes"][k]
        if set(s)!={"reads","writes","resources","checks"}:raise ValueError("invalid task scope schema")
        for path in s["reads"]+s["writes"]:
            if not within(safe_path(path),profile["paths"]):raise PermissionError("scope escalation")
        for path in s["writes"]:
            if not within(path,profile.get("write_paths",profile["paths"])):raise PermissionError("write scope escalation")
        if not isinstance(s["reads"],list) or not isinstance(s["writes"],list) or not isinstance(s["resources"],list) or any(type(x)!=str or len(x)>80 for x in s["resources"]):raise ValueError("invalid scope types")
        if not isinstance(s["checks"],list) or not 1<=len(s["checks"])<=4:raise ValueError("independent task checks required")
        for argv in s["checks"]:
            command(argv,profile["commands"])
            # Only explicitly operator-approved verification argv, not model-authored host code.
            if argv not in profile["checks"]:raise PermissionError("unapproved independent check")
        if any(profile["checks"][i] not in s["checks"] for i in required_check_indices(profile,s["writes"])):
            raise ValueError("required write-group verification omitted")
        if t.get("human_gates") or set(t.get("required_capabilities",[]))-{"text_read","text_proposal","peer_message","master_verify","review","sandbox","command","offline_install","text_edit"}:
            raise ValueError("unsupported requirement")
        scopes[k]={"reads":s["reads"],"writes":s["writes"],"resources":s["resources"],"timeout":min(300,profile["timeout"]),"request_budget":per_task}
    from .scope_compiler import root_priorities
    for k,priority in root_priorities(profile,tasks,team,scopes).items():scopes[k]["priority"]=priority
    return {"master":extension["master"],"roles":extension["roles"],"parents":extension["parents"],
            "scopes":scopes,"capacity":profile["capacity"],"run_timeout":profile["timeout"],"model":profile["model"],
            "sandbox_mode":True,"check_commands":{k:extension["scopes"][k]["checks"] for k in ids},"final_checks":profile["final_checks"]}
