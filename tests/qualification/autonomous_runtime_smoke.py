"""Actual v2 pipeline compiler, Pydantic worker, Temporal, Docker and Git CAS.
Only model responses and route-inventory approval are synthetic. This is not L01/L02.
"""
import argparse, asyncio, json, tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from pydantic_ai import ModelResponse,TextPart,ToolCallPart,models
from pydantic_ai.models.function import FunctionModel
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker,Replayer
from graph_execution_runtime.activities import Activities
from graph_execution_runtime.bootstrap import compile_bundle
from graph_execution_runtime.durable_workflows import GraphRun,AgentSession
from graph_execution_runtime.gitstage import git,inspect,Staging,inventory
from graph_execution_runtime.operator import Controller
from graph_execution_runtime.pipeline import Pipeline,PLAN,TEAM
from graph_execution_runtime.policy import digest,hash_file

models.ALLOW_MODEL_REQUESTS=False

def model_for(task):
    def respond(messages,info):
        returns={}
        for m in messages:
            for p in m.parts:
                if p.part_kind=="tool-return":returns[p.tool_name]=p.content
        k=task["id"]
        initial=[p.content for m in messages for p in m.parts if p.part_kind=="user-prompt"]
        assert any(isinstance(p,str) and "Make two contract files and review." in p and "original_plan_requirements" in p for p in initial)
        if k=="R":
            if "read_file" not in returns:return ModelResponse(parts=[ToolCallPart("read_file",{"path":"src/a.txt"})])
            assert returns["read_file"]=="contract-v2"
            return ModelResponse(parts=[TextPart("independent review")])
        if "run_approved_checks" not in returns:
            return ModelResponse(parts=[ToolCallPart("run_approved_checks",{"indices":[0]})])
        assert not returns["run_approved_checks"]["passed"]
        if k=="A":
            if "send_message" not in returns:
                return ModelResponse(parts=[ToolCallPart("send_message",{"recipient":"B","text":"contract-v2","message_key":"contract"})])
            assert json.loads(returns["send_message"])["accepted"]
            content="contract-v2"
        else:
            if "wait_messages" not in returns:
                return ModelResponse(parts=[ToolCallPart("wait_messages",{"sender":"A","kind":"HANDOFF"})])
            msg=json.loads(returns["wait_messages"])[0]
            if "acknowledge_message" not in returns:
                return ModelResponse(parts=[ToolCallPart("acknowledge_message",{"message_id":msg["id"]})])
            assert returns["acknowledge_message"] is True
            content=msg["text"]
        if "work_batch" not in returns:
            return ModelResponse(parts=[ToolCallPart("work_batch",{"operations":[{"op":"write","path":task["writes"][0],"content":content},{"op":"check","indices":[0]}]})])
        assert returns["work_batch"]["completed"][1]["passed"]
        if "submit_candidate" not in returns:
            return ModelResponse(parts=[ToolCallPart("submit_candidate",{"summary":"Checked direct handoff and scoped implementation."})])
        assert returns["submit_candidate"]["accepted"]
        if k=="A":
            from pydantic_ai.exceptions import UsageLimitExceeded
            raise UsageLimitExceeded("synthetic final response request exhausted after explicit submission")
        return ModelResponse(parts=[TextPart("submitted")])
    return FunctionModel(respond)

async def run(image,wheelhouse):
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp);root=d/"project";root.mkdir();(root/"src").mkdir();(root/"src/seed.txt").write_text("seed")
        git(root,"init","-b","main");git(root,"add",".");git(root,"commit","-m","seed")
        baseline=inspect(root);run=d/"run";run.mkdir();plan=d/"plan.md";plan.write_text("# Make two contract files and review.")
        skill_root=Path(__file__).resolve().parents[2]
        cmd=lambda f:["python","-c",f"from pathlib import Path; assert Path({f!r}).read_text()=='contract-v2'"]
        checks=[cmd("src/a.txt"),cmd("src/b.txt")]
        profile={"schema":2,"workspace":str(root),"image":image,"wheelhouse":str(wheelhouse.resolve()),
            "wheels":{f.name:hash_file(f) for f in wheelhouse.glob("*.whl")},"paths":["src"],"commands":["python"],
            "checks":checks,"final_checks":checks,"required_parallel_roots":["src/a.txt","src/b.txt"],"required_peer_handoff":True,"require_independent_review":True,"capacity":2,"timeout":300,"acknowledge":"local-trusted-docker-offline",
            "model":"openai:fixture","base_url":"http://localhost:20128/v1","approval":str(d/"approval.json"),"skill_root":str(skill_root)}
        pp=d/"profile.json";pp.write_text(json.dumps(profile));pp.chmod(0o600)
        run_id="gexec-"+uuid4().hex
        pipe=Pipeline(plan,run,skill_root);pipe.init();pipe.begin(PLAN)
        rows=[{"id":k,"duration":1,"source":"plan#scope","outcome":"contract "+k,"verification":"check contract","depends_on":deps}
              for k,deps in [("A",[]),("B",[]),("R",["A","B"])]]
        pipe.put(PLAN,"backlog.md","# Backlog");pipe.put(PLAN,"tasks.json",json.dumps({"unit":"hours","tasks":rows}));pipe.finish(PLAN,"fixture verified")
        pipe.begin(TEAM)
        pipe.put(TEAM,"team-definition.md","# Team")
        team={"agents":[{"id":x} for x in ("M","A","B","R")],"task_assignments":[{"task_id":k,"owner_agent_id":k,"leaf_cluster_id":"C"} for k in ("A","B","R")],
              "clusters":[],"staffing":{},"schedule":[],"constraints":{},"alternatives":[]}
        pipe.put(TEAM,"team-definition.json",json.dumps(team));pipe.put(TEAM,"task-graph.json",json.dumps({"tasks":[{"id":t["id"],"depends_on":t["depends_on"]} for t in rows],"couplings":[]}));pipe.finish(TEAM,"fixture verified")
        extension={"master":"M","roles":{"M":"master","A":"worker","B":"worker","R":"reviewer"},"parents":{"M":None,"A":"M","B":"M","R":"M"},
            "scopes":{"A":{"reads":[],"writes":["src/a.txt"],"resources":[],"checks":[checks[0]]},
                      "B":{"reads":[],"writes":["src/b.txt"],"resources":[],"checks":[checks[1]]},
                      "R":{"reads":["src/a.txt","src/b.txt"],"writes":[],"resources":[],"checks":checks}}}
        planning={"run_dir":str(run),"profile":profile,"workspace":str(root),"policy_sha256":digest(profile),
            "baseline":baseline,"plan":str(plan),"original_plan":str(plan),"skill_root":str(skill_root),"profile_path":str(pp),"run_id":run_id}
        st=Staging(root,profile,run_id,baseline,run/"journal/publication");st.start()
        bp=run/"bundle.json";b=compile_bundle(planning,bp,extension);spec=b["spec"]
        async with await WorkflowEnvironment.start_local() as env:
            acts=Activities(env.client,root,Path(b["journal"]),spec["model"],model_for,approved_spec=spec,bundle_path=bp)
            async with Worker(env.client,task_queue=run_id,workflows=[GraphRun,AgentSession],activities=[acts.agent_turn,acts.apply_proposal,acts.graph_ready]):
                ctl=Controller(env.client,bp)
                with patch("graph_execution_runtime.operator.approved_bundle",return_value=b):
                    await ctl.start()
                async with asyncio.timeout(240):
                    while True:
                        s=await ctl.status()
                        if s["finished"]:break
                        for k,t in s["tasks"].items():
                            if t["status"]=="verifying":
                                p=await ctl.proposal(k)
                                bad=await ctl.review_and_verify(k,t["attempt"],"reviewed","wrong")
                                assert not bad["accepted"]
                                q=await ctl.review_and_verify(k,t["attempt"],"actual scope reviewed",p["proposal_sha256"])
                                assert q["accepted"],q
                            elif t["status"]=="applied":assert (await ctl.verify(k))["decision"]["accepted"]
                            elif t["status"] in ("blocked","reconciliation_required","cancelled"):raise AssertionError({"task":k,"state":t})
                        await asyncio.sleep(.2)
                assert all(t["status"]=="done" for t in s["tasks"].values()),s
                assert any(m["status"]=="PROCESSED" for m in s["messages"])
                assert s["tasks"]["A"]["result"]["explicit_submission"] and s["tasks"]["A"]["result"]["post_submit_error"]=="UsageLimitExceeded"
                assert s["tasks"]["B"]["result"]["acknowledged_handoffs"]==s["tasks"]["A"]["result"]["sent_handoffs"]
                assert (await ctl.finalize())["passed"]
                assert st.unchanged() and st.head()!=baseline["head"]
                assert inventory(root,st.head(),profile)["src/a.txt"]==b"contract-v2"
                assert inventory(root,st.head(),profile)["src/b.txt"]==b"contract-v2"
                await Replayer(workflows=[GraphRun,AgentSession]).replay_workflow(await ctl.handle.fetch_history())
        print(json.dumps({"probe":"PASS","runtime_version":2,"policy_compiler":True,"actual_docker":True,"actual_temporal":True,
            "peer_ack":True,"post_submit_limit_recovered":True,"batched_checks":True,"master_digest_fence":True,"git_commit":True,"original_unchanged":True,"final_checks":True,"replay":True,"live_model_calls":0}))

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--image",required=True);p.add_argument("--wheelhouse",type=Path,required=True);a=p.parse_args();asyncio.run(run(a.image,a.wheelhouse))
