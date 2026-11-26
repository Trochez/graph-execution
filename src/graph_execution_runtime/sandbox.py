"""Per-attempt offline Docker execution. No project commands on the host."""
from __future__ import annotations
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4
from .policy import command, hash_file

MAX_OUTPUT=16384

def docker(argv, *, timeout=30, check=True):
    # Docker is a trusted local control plane. Do not forward provider credentials.
    env={k:v for k,v in os.environ.items() if k in ("PATH","HOME","DOCKER_HOST","DOCKER_CONTEXT","DOCKER_CONFIG","SYSTEMROOT","TMPDIR")}
    return subprocess.run(["docker",*argv],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,check=check)

class Sandbox:
    def __init__(self, root, profile):
        self.root=Path(root).resolve(strict=True);self.profile=profile
        self.name="gexec-"+uuid4().hex;self.receipts=[];self.closed=False;self.started=False
        self.remaining=24
    def __enter__(self):
        # No network, host home, Git metadata, provider credentials or Docker socket.
        # Only private disposable scratch and approved offline wheelhouse mounted.
        if "," in str(self.root) or "," in str(self.profile["wheelhouse"]):raise ValueError("unsupported mount path")
        docker(["image","inspect",self.profile["image"]])
        self.started=True
        try:
            docker(["run","--detach","--name",self.name,"--pull=never","--network=none","--read-only",
                "--cap-drop=ALL","--security-opt=no-new-privileges","--pids-limit=64","--memory=512m","--cpus=1",
                "--user",f"{os.getuid()}:{os.getgid()}","--tmpfs","/tmp:rw,noexec,nosuid,size=64m",
                "--mount",f"type=bind,src={self.root},dst=/work",
                "--mount",f"type=bind,src={Path(self.profile['wheelhouse']).resolve()},dst=/wheels,readonly",
                "--workdir","/work","--env","HOME=/tmp","--env","PYTHONDONTWRITEBYTECODE=1",
                "--env","PYTHONPATH=/work/.gexec-deps:/work:/work/src",
                "--entrypoint","python",self.profile["image"],"-c","import time; time.sleep(1800)"])
            return self
        except BaseException:
            self.close()
            raise
    def _run(self, argv, timeout):
        if self.closed or self.remaining<=0:raise RuntimeError("command budget exhausted or closed container")
        self.remaining-=1
        start=time.monotonic()
        # Spool bounded output on the host; do not retain raw unbounded stdout.
        env={k:v for k,v in os.environ.items() if k in ("PATH","HOME","DOCKER_HOST","DOCKER_CONTEXT","DOCKER_CONFIG","SYSTEMROOT","TMPDIR")}
        import threading
        p=subprocess.Popen(["docker","exec",self.name,*argv],env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        captured=bytearray();h=hashlib.sha256();count=0
        def drain():
            nonlocal count
            for b in iter(lambda:p.stdout.read(4096),b""):
                count+=len(b);h.update(b)
                if len(captured)<MAX_OUTPUT:captured.extend(b[:MAX_OUTPUT-len(captured)])
        t=threading.Thread(target=drain,daemon=True);t.start()
        timed_out=False
        try:p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out=True
            # Killing the CLI alone does not kill docker exec; remove the container.
            try:self.close()
            finally:p.kill();p.wait()
        t.join(timeout=5)
        r={"argv":argv,"exit_code":None if timed_out else p.returncode,"timeout":timed_out,
           "output":captured.decode("utf-8",errors="replace"),"output_sha256":h.hexdigest(),"output_bytes":count,
           "truncated":count>MAX_OUTPUT,"elapsed_ms":round((time.monotonic()-start)*1000)}
        self.receipts.append(r);return r
    def run(self,argv,timeout=60):
        return self._run(command(argv,self.profile["commands"]),min(60,max(1,timeout)))
    def install(self,wheels):
        if not isinstance(wheels,list) or not wheels or len(wheels)>20 or len(set(wheels))!=len(wheels):raise ValueError("invalid wheel list")
        for w in wheels:
            if w not in self.profile["wheels"] or hash_file(Path(self.profile["wheelhouse"])/w)!=self.profile["wheels"][w]:
                raise PermissionError("unapproved wheel or hash changed")
        # Direct wheel paths, no dependency discovery or package indexes.
        return self._run(["python","-m","pip","install","--no-index","--no-deps","--no-cache-dir","--target","/work/.gexec-deps",*["/wheels/"+w for w in wheels]],60)
    def close(self):
        if self.closed:return
        if self.started:
            docker(["rm","-f",self.name],check=False)
            r=docker(["ps","-a","--filter","name=^/"+self.name+"$","--format","{{.Names}}"])
            if r.stdout.strip():raise RuntimeError("container cleanup not confirmed")
        self.closed=True
    def __exit__(self,*exc):self.close()
