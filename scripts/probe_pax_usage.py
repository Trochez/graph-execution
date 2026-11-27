"""Two tiny live requests to check the approved endpoint's actual usage reporting."""
import argparse,asyncio,getpass,json,os,tempfile
from pathlib import Path
from pydantic_ai import Agent
from graph_execution_runtime.budget import Budget
from graph_execution_runtime.operator import model_factory,discover_models
from graph_execution_runtime.config import check_approval,load_json

async def run(a):
    key=os.environ.get("GEXEC_PROBE_API_KEY") or getpass.getpass("Provider API key (local only): ")
    check_approval({"model":a.model},load_json(a.approval),a.base_url,await discover_models(a.base_url,key))
    with tempfile.TemporaryDirectory(prefix="gexec-usage-probe-") as tmp:
        b=Budget(Path(tmp)/"budget.db","master",2,"plan")
        agent=Agent(model_factory(a.base_url,key,a.model,b),model_settings={"max_tokens":256})
        await agent.run("Reply only OK.")
        async with agent.run_stream("Reply only OK.") as result:
            await result.get_output()
        s=b.summary()
        passed=s["reserved_requests"]==2 and s["settled_requests"]==2 and s["provider_reported_tokens"]>0
        print(json.dumps({"probe":"PASS" if passed else "FAIL","scope":"two live usage-reporting probes only","budget":s},indent=2))
        return 0 if passed else 2
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--base-url",required=True);p.add_argument("--model",required=True)
    p.add_argument("--approval",type=Path,default=Path.home()/".config/graph-execution/pax/model-policy.json")
    raise SystemExit(asyncio.run(run(p.parse_args())))
