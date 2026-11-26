"""Git object-based staging: no checkout, hooks, project shell, or original worktree writes."""
from __future__ import annotations
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from .policy import safe_path, within
from .pipeline import atomic_json

def git(root,*args,input=None,env=None):
    e={k:v for k,v in os.environ.items() if k in ("PATH","HOME","SYSTEMROOT","TMPDIR")}
    e.update(GIT_CONFIG_NOSYSTEM="1",GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT="0",
             GIT_AUTHOR_NAME="gexec",GIT_AUTHOR_EMAIL="gexec@local.invalid",GIT_COMMITTER_NAME="gexec",GIT_COMMITTER_EMAIL="gexec@local.invalid")
    e.update(env or {})
    return subprocess.run(["git","-C",str(root),"-c","core.hooksPath="+os.devnull,*args],input=input,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=e,timeout=30,check=True).stdout

def inspect(root):
    root=Path(root).resolve(strict=True)
    if Path(git(root,"rev-parse","--show-toplevel").decode().strip()).resolve()!=root:raise ValueError("workspace must be Git root")
    if git(root,"status","--porcelain=v1","--untracked-files=all"):raise ValueError("target must be clean")
    return {"head":git(root,"rev-parse","HEAD").decode().strip(),"branch":git(root,"symbolic-ref","HEAD").decode().strip()}

def inventory(root,head,profile):
    result={}
    for row in git(root,"ls-tree","-rz","-r",head).split(b"\0"):
        if not row:continue
        meta,raw=row.split(b"\t",1);mode,kind,oid=meta.decode().split()
        path=raw.decode("utf-8")
        if not within(path,profile["paths"]):continue
        safe_path(path)
        if mode!="100644" or kind!="blob":raise ValueError("unsupported tracked file mode")
        data=git(root,"cat-file","blob",oid)
        if len(data)>65536:raise ValueError("oversize tracked input")
        data.decode("utf-8")
        result[path]=data
        if len(result)>250:raise ValueError("inventory bound exceeded")
    if len({p.casefold() for p in result})!=len(result):raise ValueError("case-insensitive path collision")
    return result

def materialize(data,dest):
    for name,value in data.items():
        p=Path(dest)/safe_path(name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)

def scratch_inventory(root,profile):
    root=Path(root);out={}
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in dirs[:]:
            p=Path(directory)/name
            if p.is_symlink():raise ValueError("symlink export denied")
            if name in (".gexec-deps",".pytest_cache","__pycache__"):
                dirs.remove(name);continue
            safe_path(p.relative_to(root).as_posix())
        for name in files:
            p=Path(directory)/name;rel=p.relative_to(root).as_posix()
            safe_path(rel)
            if p.is_symlink() or not p.is_file() or p.stat().st_nlink!=1 or p.stat().st_mode&0o111 or not within(rel,profile["paths"]):
                raise ValueError("forbidden scratch export")
            if p.stat().st_size>65536:raise ValueError("export size")
            d=p.read_bytes();d.decode("utf-8");out[rel]=d
            if len(out)>250:raise ValueError("inventory bound")
    if len({p.casefold() for p in out})!=len(out):raise ValueError("path collision")
    return out

def sha(value):
    return "absent" if value is None else hashlib.sha256(value).hexdigest()

def proposal(before,after,writes):
    edits=[]
    for path in sorted(before.keys()|after.keys()):
        a,b=before.get(path),after.get(path)
        if a==b:continue
        if path not in writes:raise PermissionError("change outside exact task scope")
        edits.append({"path":path,"base":sha(a),"content":None if b is None else b.decode(),"sha256":sha(b)})
    if len(edits)>20 or sum(len((e["content"] or "").encode()) for e in edits)>262144:raise ValueError("proposal budget")
    return edits

def apply_edits(before,edits,writes):
    result=dict(before);seen=set()
    for e in edits:
        path=safe_path(e["path"])
        if set(e)!={"path","base","content","sha256"} or path in seen or path not in writes or sha(result.get(path))!=e["base"]:
            raise ValueError("stale or unauthorized proposal")
        seen.add(path);value=None if e["content"] is None else e["content"].encode("utf-8")
        if sha(value)!=e["sha256"] or (value is not None and len(value)>65536):raise ValueError("proposal hash/size")
        if value is None:result.pop(path,None)
        else:result[path]=value
    if proposal(before,result,writes)!=sorted(edits,key=lambda e:e["path"]):raise ValueError("invalid or redundant proposal")
    return result

class Staging:
    def __init__(self,root,profile,run_id,baseline,journal):
        self.root=Path(root);self.profile=profile;self.baseline=baseline;self.journal=Path(journal)
        if not re.fullmatch(r"gexec-[a-f0-9]{32}",run_id):raise ValueError("invalid run id")
        self.ref="refs/heads/"+run_id
    def start(self):
        git(self.root,"update-ref",self.ref,self.baseline["head"],"0"*40)
    def head(self):return git(self.root,"rev-parse",self.ref).decode().strip()
    def unchanged(self):return inspect(self.root)==self.baseline
    def publish(self,task,attempt,edits,verify,*,inputs=None):
        # Only called by the serialized, master-approved integration activity.
        self.journal.mkdir(parents=True,exist_ok=True)
        key=hashlib.sha256(f"{task['id']}:{attempt}".encode()).hexdigest()
        intent=self.journal/(key+".intent.json");done=self.journal/(key+".done.json")
        if intent.exists():
            p=json.loads(intent.read_text());current=self.head()
            if current==p["new"]:
                if not done.exists():atomic_json(done,p)
                return p
            if current!=p["old"]:raise RuntimeError("publication reconciliation required")
            git(self.root,"update-ref",self.ref,p["new"],p["old"]);atomic_json(done,p);return p
        if not self.unchanged():raise RuntimeError("original checkout changed")
        old=self.head();before=inventory(self.root,old,self.profile)
        if inputs is not None and any(sha(before.get(p))!=v for p,v in inputs.items()):raise ValueError("stale task input")
        after=apply_edits(before,edits,task["writes"])
        checks=verify(after)
        if not checks or any(x["exit_code"]!=0 for x in checks):raise ValueError("independent candidate checks failed")
        if not edits:return {"old":old,"new":old,"checks":checks,"applied":True,"files":[]}
        with tempfile.TemporaryDirectory(dir=self.journal) as d:
            idx=str(Path(d)/"index");env={"GIT_INDEX_FILE":idx}
            git(self.root,"read-tree",old,env=env)
            for e in edits:
                if e["content"] is None:git(self.root,"update-index","--force-remove","--",e["path"],env=env)
                else:
                    oid=git(self.root,"hash-object","-w","--stdin",input=e["content"].encode()).decode().strip()
                    git(self.root,"update-index","--add","--cacheinfo","100644",oid,e["path"],env=env)
            tree=git(self.root,"write-tree",env=env).decode().strip()
            new=git(self.root,"commit-tree",tree,"-p",old,"-m",f"gexec task {task['id']} attempt {attempt}").decode().strip()
        record={"old":old,"new":new,"proposal_sha256":hashlib.sha256(json.dumps(edits,sort_keys=True).encode()).hexdigest(),"checks":checks,"applied":True,"files":[{"path":e["path"],"sha256":e["sha256"]} for e in edits]}
        atomic_json(intent,record)
        if not self.unchanged():raise RuntimeError("original checkout changed before CAS")
        git(self.root,"update-ref",self.ref,new,old);atomic_json(done,record)
        return record
