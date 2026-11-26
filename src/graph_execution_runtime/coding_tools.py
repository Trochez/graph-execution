"""Scoped agent tools and independent container verification for autonomous runs."""
from __future__ import annotations
import asyncio
import hashlib
import json
import tempfile
from pathlib import Path
from .sandbox import Sandbox
from .gitstage import inventory,materialize,scratch_inventory,proposal,sha,Staging
from .policy import safe_path
from .pipeline import atomic_json

# Fixed, trusted helper executes INSIDE the restricted container, not on host.
FILE_OP = """
import json, os, stat, sys
from pathlib import Path
op,path,value=json.loads(sys.argv[1])
root=Path('/work')
p=root
for piece in path.split('/'):
    p=p/piece
    if p.is_symlink():raise ValueError('symlink denied')
if p.exists() and (not p.is_file() or p.stat().st_nlink!=1):raise ValueError('not regular single-link file')
if op=='read':
    print(json.dumps(p.read_text() if p.exists() and p.stat().st_size<=65536 else None))
elif op=='write':
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(value)
elif op=='delete':
    p.unlink(missing_ok=True)
"""

def checks_in_sandbox(data,profile,commands):
    with tempfile.TemporaryDirectory(prefix="gexec-check-") as d:
        materialize(data,d)
        with Sandbox(d,profile) as s:
            results=[]
            if profile["wheels"]:
                r=s.install(sorted(profile["wheels"]));results.append(r)
                if r["exit_code"]!=0:return results
            for cmd in commands:
                r=s.run(cmd);results.append(r)
                if r["exit_code"]!=0:break
            return results

def stage_for(bundle):
    return Staging(Path(bundle["workspace"]),bundle["profile"],bundle["spec"]["workflow_id"],bundle["baseline"],Path(bundle["journal"])/"publication")

def compact_receipts(receipts):
    return [{k:v for k,v in r.items() if k!="output"} for r in receipts]

class CodingSession:
    def __init__(self,bundle,task,attempt):
        self.bundle=bundle;self.task=task;self.attempt=attempt
        self.staging=stage_for(bundle);self.profile=bundle["profile"]
        self.base_revision=self.staging.head()
        self.before=inventory(self.staging.root,self.base_revision,self.profile)
        self.tmp=tempfile.TemporaryDirectory(prefix="gexec-attempt-",dir=Path(bundle["journal"]))
        self.root=Path(self.tmp.name)
        materialize(self.before,self.root)
        self.sandbox=Sandbox(self.root,self.profile)
        self.seen={};self.last_signature=None;self.repeated=0;self.finished=False
        self.record=Path(bundle["journal"])/"attempts"/(task["id"]+"-"+str(attempt)+".json")
        self.inputs={p:sha(self.before.get(p)) for p in sorted(set(task["reads"]+task["writes"]))}
        from .budget import Budget
        self.budget=Budget(bundle["budget_db"],task["id"],task["request_budget"])
    def start(self):
        self.sandbox.__enter__()
        atomic_json(self.record,{"status":"started","container":self.sandbox.name,"attempt":self.attempt,"base":self.base_revision})
    def check(self,path,write=False):
        safe_path(path)
        if path not in (self.task["writes"] if write else self.task["reads"]+self.task["writes"]):raise PermissionError("path outside assignment")
    def file_op(self,op,path,value=None):
        self.budget.tool()
        self.check(path,op!="read")
        if value is not None and len(value.encode())>65536:raise ValueError("file size")
        r=self.sandbox._run(["python","-c",FILE_OP,json.dumps([op,path,value])],10)
        if r["exit_code"]!=0:raise ValueError("file operation failed")
        if op=="read":return json.loads(r["output"])
        return "OK"
    def repeat(self,key,progress=False):
        if progress:self.repeated=0;self.last_signature=None;return
        if key==self.last_signature:self.repeated+=1
        else:self.last_signature=key;self.repeated=1
        if self.repeated>=3:raise RuntimeError("NO_PROGRESS_LOOP")
    def install(self,wheels):
        self.budget.tool();return self.sandbox.install(wheels)
    def run(self,argv,timeout):
        self.budget.tool()
        r=self.sandbox.run(argv,timeout)
        self.repeat(json.dumps([argv,r["exit_code"],r["output_sha256"]]))
        return r
    def attach(self,agent):
        @agent.tool_plain
        def list_paths()->list[str]:
            """List exact authorized input and output paths."""
            return sorted(set(self.task["reads"]+self.task["writes"]))
        @agent.tool_plain
        async def search_text(query:str)->list[dict]:
            """Search bounded authorized text files."""
            if not query or len(query)>256:return []
            hits=[]
            for p in list_paths()[:20]:
                s=await asyncio.to_thread(self.file_op,"read",p)
                if s:
                    hits.extend({"path":p,"line":i+1,"text":line[:300]} for i,line in enumerate(s.splitlines()) if query in line)
                if len(hits)>=20:break
            return hits[:20]
        @agent.tool_plain
        async def read_file(path:str)->str:
            """Read authorized current scratch text."""
            try:return (await asyncio.to_thread(self.file_op,"read",path)) or "ABSENT"
            except (ValueError,PermissionError):return "DENIED"
        @agent.tool_plain
        async def write_file(path:str,content:str)->str:
            """Write a complete authorized text file, creating parent directories."""
            try:
                r=await asyncio.to_thread(self.file_op,"write",path,content);self.repeat(None,True);return r
            except (ValueError,PermissionError):return "DENIED"
        @agent.tool_plain
        async def delete_file(path:str)->str:
            """Delete an authorized text file."""
            try:
                r=await asyncio.to_thread(self.file_op,"delete",path);self.repeat(None,True);return r
            except (ValueError,PermissionError):return "DENIED"
        @agent.tool_plain
        async def rename_file(source:str,destination:str)->str:
            """Rename via checked copy and delete within exact write scope."""
            try:
                self.check(source,True);self.check(destination,True)
                s=await asyncio.to_thread(self.file_op,"read",source)
                if s is None:return "ABSENT"
                if await asyncio.to_thread(self.file_op,"read",destination) is not None:return "DENIED: destination exists"
                await asyncio.to_thread(self.file_op,"write",destination,s)
                await asyncio.to_thread(self.file_op,"delete",source);self.repeat(None,True);return "OK"
            except (ValueError,PermissionError):return "DENIED"
        @agent.tool_plain
        async def run_command(argv:list[str],timeout:int=60)->dict:
            """Run approved Python or pytest argv in the disposable offline container."""
            try:return await asyncio.to_thread(self.run,argv,timeout)
            except (PermissionError,ValueError):return {"denied":True}
        @agent.tool_plain
        async def install_dependencies(wheels:list[str])->dict:
            """Install approved exact wheel filenames only, offline."""
            try:return await asyncio.to_thread(self.install,wheels)
            except (PermissionError,ValueError):return {"denied":True}
        @agent.tool_plain
        async def run_tests(argv:list[str])->dict:
            """Run actual approved test argv in the attempt sandbox."""
            return await run_command(argv,60)
    def finish(self):
        # Stop untrusted code before host inspection.
        self.sandbox.close()
        after=scratch_inventory(self.root,self.profile)
        edits=proposal(self.before,after,self.task["writes"])
        facts={"base_revision":self.base_revision,"input_hashes":self.inputs,"edits":edits,
               "commands":compact_receipts(self.sandbox.receipts),"attempt":self.attempt,"container_stopped":True}
        facts["proposal_sha256"]=hashlib.sha256(json.dumps(edits,sort_keys=True).encode()).hexdigest()
        atomic_json(self.record,{"status":"submitted",**facts})
        self.finished=True;return facts
    def close(self):
        self.sandbox.close()
        if not self.finished:atomic_json(self.record,{"status":"discarded","container_stopped":True,"attempt":self.attempt,"commands":compact_receipts(self.sandbox.receipts)})
        self.tmp.cleanup()
