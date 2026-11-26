"""Compile a master-generated extension against a previously approved project policy."""
from pathlib import Path
from .config import prepare,load_json
from .policy import compile_settings,digest,validate_profile
from .pipeline import Pipeline,PLAN,TEAM,atomic_json
from .gitstage import inspect,Staging
from .cli import private_json

def compile_bundle(planning,bundle_path,extension):
    run=Path(planning["run_dir"]);profile=planning["profile"];root=Path(planning["workspace"])
    validate_profile(profile,root)
    if digest(profile)!=planning["policy_sha256"] or inspect(root)!=planning["baseline"]:
        raise PermissionError("policy or original checkout changed")
    p=Pipeline(Path(planning["plan"]),run,Path(planning["skill_root"]))
    tp=run/PLAN/"tasks.json";tm=run/TEAM/"team-definition.json"
    p.bind(tp,tm)
    if bundle_path.exists():
        from .operator import load_bundle
        b=load_bundle(bundle_path)
        if b["extension_sha256"]!=digest(extension):raise PermissionError("cannot change prepared extension")
        return b
    settings=compile_settings(profile,load_json(tp),load_json(tm),extension)
    settings["policy_sha256"]=planning["policy_sha256"]
    spec=prepare(planning["run_id"],p.plan,tp,tm,settings)
    journal=run/"journal";journal.mkdir(mode=0o700,exist_ok=True)
    extension_path=run/"execution-spec.json"
    if extension_path.exists():
        if digest(load_json(extension_path))!=digest(extension):raise ValueError("execution extension already frozen")
    else:private_json(extension_path,extension)
    bundle={"spec":spec,"pipeline":str(run),"workspace":str(root),"skill_root":planning["skill_root"],
            "journal":str(journal),"base_url":profile["base_url"],"approval":profile["approval"],"profile":profile,
            "baseline":planning["baseline"],"extension_sha256":digest(extension),"profile_path":planning["profile_path"],
            "original_plan":planning["original_plan"],"budget_db":str(run/"budget.db"),
            "sources":{"plan":str(p.plan),"tasks":str(tp),"team":str(tm)},
            "check_commands":settings["check_commands"],"final_checks":settings["final_checks"]}
    # Supervisor creates this run's branch before invoking the master.
    if Staging(root,profile,spec["workflow_id"],bundle["baseline"],journal/"publication").head()!=bundle["baseline"]["head"]:
        raise PermissionError("unexpected initial staging head")
    private_json(bundle_path,bundle)
    return bundle
