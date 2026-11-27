import json
import tempfile
from pathlib import Path
from graph_execution_runtime.pipeline import Pipeline,PLAN,TEAM
from graph_execution_runtime.config import prepare

root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as d:
    d=Path(d);plan=d/"plan.md";plan.write_text("# Create a.txt")
    p=Pipeline(plan,d/"run",root);p.init()
    try:p.begin(TEAM)
    except ValueError:pass
    else:raise AssertionError("stage barrier bypass")
    p.begin(PLAN)
    tasks={"unit":"hours","tasks":[{"id":"T01","duration":1,"source":"plan.md#Create","outcome":"create a","verification":"file exists","depends_on":[]}]}
    p.put(PLAN,"backlog.md","# Backlog")
    p.put(PLAN,"tasks.json",json.dumps(tasks))
    p.finish(PLAN,"fixture verified")
    p.begin(TEAM)
    p.put(TEAM,"team-definition.md","# Team")
    p.put(TEAM,"task-graph.json",json.dumps({"tasks":[{"id":"T01","depends_on":[]}],"couplings":[]}))
    team={"agents":[{"id":"M"},{"id":"A"}],"task_assignments":[{"task_id":"T01","owner_agent_id":"A","leaf_cluster_id":"C01"}],
          "clusters":[],"staffing":{},"schedule":[],"constraints":{},"alternatives":[]}
    p.put(TEAM,"team-definition.json",json.dumps(team))
    p.finish(TEAM,"fixture verified")
    tasks_path=p.run_dir/PLAN/"tasks.json";team_path=p.run_dir/TEAM/"team-definition.json"
    settings={"roles":{"M":"master","A":"worker"},"parents":{"M":None,"A":"M"},"master":"M","model":"openai:approved-fixture",
              "scopes":{"T01":{"writes":["a.txt"],"reads":[]}}}
    spec=prepare("fixture",plan,tasks_path,team_path,settings)
    assert spec["tasks"]["T01"]["owner"]=="A"
    p.start_executor(tasks_path,team_path)
    output=d/"execution.json";output.write_text("{}")
    s=p.finish_executor([output],"verified fixture")
    assert all(s["stages"][stage]["status"]=="completed" for stage in s["stages"])
    plan.write_text("changed")
    try:p.bind(tasks_path,team_path)
    except ValueError:pass
    else:raise AssertionError("stale fingerprint accepted")
print(json.dumps({"probe":"PASS","stage_barrier":True,"legacy_translator":True,"stale_input_rejected":True}))
