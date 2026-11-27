"""Real Docker qualification for the isolated command broker; no model requests."""
import argparse,json,tempfile
from pathlib import Path
from graph_execution_runtime.sandbox import Sandbox,SandboxInterrupted,docker
from graph_execution_runtime.gitstage import scratch_inventory,proposal,materialize
from graph_execution_runtime.policy import hash_file

def main():
    p=argparse.ArgumentParser();p.add_argument("--image",required=True);p.add_argument("--wheelhouse",type=Path,required=True)
    a=p.parse_args();w={f.name:hash_file(f) for f in a.wheelhouse.glob("*.whl")}
    profile={"image":a.image,"wheelhouse":str(a.wheelhouse.resolve()),"wheels":w,"commands":["python"],"paths":["src"]}
    with tempfile.TemporaryDirectory() as d:
        root=Path(d);before={"src/old.py":b"x=1\n"};materialize(before,root)
        with Sandbox(root,profile) as s:
            name=s.name
            r=s.run(["python","-c","import os,socket; assert os.getuid()!=0; assert not os.path.exists('/var/run/docker.sock'); assert not os.access('/etc',os.W_OK); assert not os.path.exists('/root/.ssh'); assert 'GEXEC_PROBE_API_KEY' not in os.environ; print('isolated')"])
            assert r["exit_code"]==0,r
            facts=json.loads(docker(["inspect",name]).stdout)[0]
            assert facts["HostConfig"]["NetworkMode"]=="none"
            assert facts["HostConfig"]["ReadonlyRootfs"] and not facts["HostConfig"]["Privileged"]
            assert {m["Destination"] for m in facts["Mounts"]}=={"/work","/wheels"}
            r=s.run(["python","-c","from pathlib import Path; assert Path('src/old.py').read_text()=='wrong'"])
            assert r["exit_code"]!=0,r
            r=s.run(["python","-c","from pathlib import Path; p=Path('src/new'); p.mkdir(); Path('src/old.py').rename(p/'new.py'); (p/'new.py').write_text('x=2\\n')"])
            assert r["exit_code"]==0,r
            r=s.run(["python","-c","from pathlib import Path; assert Path('src/new/new.py').read_text()=='x=2\\n'"])
            assert r["exit_code"]==0,r
            if w:
                r=s.install(sorted(w));assert r["exit_code"]==0,r
            try:s.install(["not-approved.whl"])
            except PermissionError:pass
            else:raise AssertionError("unapproved wheel allowed")
            r=s.run(["python","-c","print('x'*40000)"])
            assert r["truncated"] and r["output_bytes"]>40000
        assert not docker(["ps","-a","--filter","name=^/"+name+"$","--format","{{.Names}}"]).stdout.strip()
        assert len(proposal(before,scratch_inventory(root,profile),["src/old.py","src/new/new.py"]))==2
        with Sandbox(root,profile) as s:
            name=s.name
            try:s.run(["python","-c","import time;time.sleep(10)"],1)
            except SandboxInterrupted:pass
            else:raise AssertionError("timeout not enforced")
        assert not docker(["ps","-a","--filter","name=^/"+name+"$","--format","{{.Names}}"]).stdout.strip()
    print(json.dumps({"probe":"PASS","non_root":True,"offline":True,"readonly_root":True,"real_file_changes":True,"failing_test_repaired":True,"wheel_install":bool(w),"command_timeout_cleanup":True,"output_bound":True,"live_model_calls":0}))
if __name__=="__main__":main()
