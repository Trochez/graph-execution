"""Import the actual packaged Pax bridge and exercise the planning entrypoint offline."""
import json
import os
import tempfile
from pathlib import Path
from pydantic_ai import models
models.ALLOW_MODEL_REQUESTS=False
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as d:
    d=Path(d);plan=d/"plan.md";plan.write_text("# Synthetic plan")
    config=d/"planning.json"
    config.write_text(json.dumps({"plan":str(plan),"workspace":str(d),"skill_root":str(root),"run_dir":str(d/"run"),
        "base_url":"http://localhost:20128/v1","model":"openai:fixture","read_paths":[]}))
    os.environ.update(GEXEC_RUN_BUNDLE=str(d/"future-bundle.json"),GEXEC_PIPELINE_CONFIG=str(config),GEXEC_PROBE_API_KEY="synthetic-not-a-credential")
    from graph_execution_runtime import pax_bridge as b
    assert b.gexec_runtime_info()["planning"]
    assert b.gexec_plan_source()=="# Synthetic plan"
    s=b.gexec_pipeline_init()
    assert all(r["status"]=="pending" for r in s["stages"].values())
    assert b.gexec_planning_read("unapproved.txt")=="DENIED"
print(json.dumps({"probe":"PASS","actual_bridge_import":True,"planning_tools":True,"live_model_calls":0}))
