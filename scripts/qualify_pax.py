"""Run one actual live qualification scenario with a fresh fixture; no simulated decisions."""
from __future__ import annotations
import argparse, getpass, json, os, re, signal, subprocess, sys, time
from pathlib import Path
from graph_execution_runtime.gitstage import git,inspect,inventory
from graph_execution_runtime.coding_tools import checks_in_sandbox,compact_receipts
from graph_execution_runtime.sandbox import docker
from graph_execution_runtime.cli import private_json
from graph_execution_runtime.process_control import matching_run,read_terminal,recover_receipt

def main():
    p=argparse.ArgumentParser()
    for k in ("image","base-url","model"):p.add_argument("--"+k,required=True)
    p.add_argument("--output",required=True,type=Path);p.add_argument("--scenario",choices=("L01","L02"),required=True)
    p.add_argument("--approval",type=Path,default=Path.home()/".config/graph-execution/pax/model-policy.json")
    a=p.parse_args();out=a.output.resolve()
    # Fresh fixture and evidence for each scenario. Never overwrite a previous run.
    subprocess.run([sys.executable,str(Path(__file__).with_name("create_pax_fixture.py")),"--output",str(out),
                    "--image",a.image,"--base-url",a.base_url,"--model",a.model,"--approval",str(a.approval)],check=True)
    profile=json.loads((out/"profile.json").read_text());root=out/"project";baseline=inspect(root)
    initial=compact_receipts(checks_in_sandbox(inventory(root,baseline["head"],profile),profile,[profile["checks"][0]]))
    if not initial or initial[-1]["exit_code"]==0:raise RuntimeError("fixture baseline failure not reproduced")
    gexec=Path(sys.executable).parent/"gexec"
    subprocess.run([str(gexec),"setup","--workspace",str(root),"--profile",str(out/"profile.json")],check=True)
    env=dict(os.environ)
    env.pop("GEXEC_QUALIFICATION_FAULT_CONTROL",None)
    if not env.get("GEXEC_PROBE_API_KEY"):env["GEXEC_PROBE_API_KEY"]=getpass.getpass("Provider API key (local only): ")
    control=out/"fault-control";control.mkdir(mode=0o700)
    if a.scenario=="L02":env["GEXEC_QUALIFICATION_FAULT_CONTROL"]=str(control)
    facts=[];run=None;watchdog=False;terminal_seen=None
    state_root=Path.home()/".local/state/graph-execution/runs"
    with (out/"runner.stdout").open("wb") as stdout,(out/"runner.stderr").open("wb") as stderr:
        proc=subprocess.Popen([str(gexec),"run","--plan",str(out/"PLAN.md"),"--workspace",str(root)],env=env,stdout=stdout,stderr=stderr)
        deadline=time.monotonic()+1250
        while proc.poll() is None and time.monotonic()<deadline:
            if run is None:run=matching_run(state_root,root,out/"PLAN.md")
            if read_terminal(run) is not None:
                if terminal_seen is None:terminal_seen=time.monotonic()
                if time.monotonic()-terminal_seen>8:break
            if a.scenario=="L02":
                for kind in ("worker","master"):
                    marker=control/(kind+".json");release=control/(kind+".released")
                    if not marker.exists() or release.exists():continue
                    f=json.loads(marker.read_text());run_id=f["run_id"]
                    if not re.fullmatch(r"gexec-[a-f0-9]{32}",run_id):raise ValueError("fault run identity")
                    run=Path.home()/".local/state/graph-execution/runs"/run_id
                    planning=json.loads((run/"planning.json").read_text())
                    if Path(planning["workspace"])!=root:raise PermissionError("fault target mismatch")
                    if kind=="worker":
                        if not re.fullmatch(r"gexec-[a-f0-9]{32}",f["container"]):raise ValueError("invalid container name")
                        attempt=json.loads((run/"journal/attempts"/(f["task"]+"-1.json")).read_text())
                        if attempt["container"]!=f["container"]:raise PermissionError("container ownership mismatch")
                        docker(["rm","-f",f["container"]])
                        if docker(["ps","-a","--filter","name=^/"+f["container"]+"$","--format","{{.Names}}"]).stdout.strip():raise RuntimeError("container still present")
                    else:
                        pid=int(f["pid"]);m=json.loads((run/"master-1.json").read_text())
                        if m["pid"]!=pid or int(subprocess.check_output(["ps","-p",str(pid),"-o","ppid="]).strip())!=proc.pid:
                            raise PermissionError("master ownership mismatch")
                        os.kill(pid,signal.SIGKILL)
                    facts.append({"kind":kind,"triggered":True,"run_id":run_id,"task":f["task"]})
                    private_json(release,{"released":True})
            time.sleep(.2)
        if proc.poll() is None:
            watchdog=True
            proc.terminate()
            try:proc.wait(timeout=75)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
    if run is None:run=matching_run(state_root,root,out/"PLAN.md")
    r,recovery=recover_receipt(out/"runner.stdout",run,proc.returncode,watchdog)
    predicates={"runtime_go":r.get("decision")=="GO" and proc.returncode==0,
                "original_unchanged":inspect(root)==baseline,"baseline_failure":initial[-1]["exit_code"]!=0,
                "final_oracle":False,"all_skills_loaded":False,"peer_ack":False,"actual_worker_install":False,
                "actual_worker_failed_and_passed_test":False,"independent_reviewer":False,"overlap":False}
    if r.get("records"):
        run=Path(r["records"])
        predicates["all_skills_loaded"]=all((run/"skill-loads"/(name+".json")).is_file() for name in ("gexec","critical-path-planner","backlog-team-designer","native-plan-executor"))
        try:
            b=json.loads((run/"bundle.json").read_text());s=json.loads((run/"journal/records/execution.json").read_text())["snapshot"]
            predicates["peer_ack"]=any(m["status"]=="PROCESSED" and m["sender"]!=b["spec"]["master"] and m["recipient"]!=b["spec"]["master"] for m in s["messages"])
            predicates["independent_reviewer"]=any(b["spec"]["agents"][t["owner"]]["role"]=="reviewer" and not t["writes"] and s["tasks"][k]["status"]=="done" for k,t in b["spec"]["tasks"].items())
            active=set()
            for e in s["events"]:
                if e["kind"]=="in_progress":active.add(e["task"])
                elif e["kind"] in ("verifying","blocked","cancelled","pending"):active.discard(e["task"])
                if len(active)>=2:predicates["overlap"]=True
            for af in (run/"journal/attempts").glob("*.json"):
                ar=json.loads(af.read_text());commands=ar.get("commands",[])
                predicates["actual_worker_install"]|=any(c["argv"][:3]==["python","-m","pip"] and c["exit_code"]==0 for c in commands)
                tests=[c for c in commands if c["argv"][:3]==["python","-m","unittest"]]
                predicates["actual_worker_failed_and_passed_test"]|=any(t["argv"]==profile["checks"][0] and t["exit_code"] not in (0,None) and any(x["argv"]==t["argv"] and x["exit_code"]==0 for x in tests[i+1:]) for i,t in enumerate(tests))
            if (run/"journal/records/final-checks.json").is_file():
                final=json.loads((run/"journal/records/final-checks.json").read_text())
                predicates["final_oracle"]=final["passed"] and final["commit"]==r.get("implementation_commit") and any(x.get("argv")==["python","/oracle/verify.py"] and x["exit_code"]==0 for x in final["checks"])
            if a.scenario=="L02":
                predicates["both_faults"]=len(facts)==2 and all(f["run_id"]==r.get("run_id") for f in facts)
                predicates["master_recovered"]=r.get("master_restarts")==1
                predicates["worker_recovered"]=any(e["kind"]=="worker_recovery" for e in s["events"]) and any(t["attempt"]==2 and t["status"]=="done" for t in s["tasks"].values())
        except (OSError,KeyError,ValueError,TypeError):pass
    receipt={"scenario":a.scenario,"probe":"PASS" if all(predicates.values()) else "FAIL","predicates":predicates,
             "run_id":r.get("run_id"),"runtime_exit":proc.returncode,"budget":r.get("budget"),"faults":facts,
             "implementation_commit":r.get("implementation_commit"),"receipt_recovery":recovery,"cleanup":r.get("cleanup"),"effective_model":"unknown","scope":"fixture evidence only; not full release GO"}
    private_json(out/"qualification-receipt.json",receipt);print(json.dumps(receipt,indent=2));return 0 if receipt["probe"]=="PASS" else 2
if __name__=="__main__":raise SystemExit(main())
