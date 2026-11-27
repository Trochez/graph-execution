"""Credential-free policy, budget, real Git and mailbox checks."""
import json
import tempfile
import unittest
from pathlib import Path
from graph_execution_runtime.policy import compile_settings,safe_path
from graph_execution_runtime.gitstage import git,inspect,inventory,Staging,proposal,sha
from graph_execution_runtime.budget import Budget
from graph_execution_runtime.live_mailbox import valid_packet,can_recover

class Autonomous(unittest.TestCase):
    def test_policy(self):
        p={"paths":["src","tests"],"commands":["python"],"checks":[["python","-m","unittest"]],
           "final_checks":[["python","-m","unittest","discover"]],"capacity":2,"timeout":1200,"model":"openai:fixture"}
        tasks={"tasks":[{"id":"A"}]};team={"agents":[{"id":"M"},{"id":"W"}]}
        e={"master":"M","roles":{"M":"master","W":"worker"},"parents":{"M":None,"W":"M"},
           "scopes":{"A":{"reads":[],"writes":["src/a.py"],"resources":[],"checks":p["checks"]}}}
        self.assertTrue(compile_settings(p,tasks,team,e)["sandbox_mode"])
        e["scopes"]["A"]["writes"]=["outside.py"]
        with self.assertRaises(PermissionError):compile_settings(p,tasks,team,e)
        for name in ("../secret","src/.env","src/a.pem","src//x","src/.git"):
            with self.assertRaises(ValueError):safe_path(name)
    def test_budget(self):
        with tempfile.TemporaryDirectory() as d:
            b=Budget(Path(d)/"b.db","A",1)
            b.reserve(b'{"max_tokens":100}')
            with self.assertRaises(RuntimeError):Budget(Path(d)/"b.db","A",1).reserve(b'{"max_tokens":100}')
            self.assertEqual(b.summary()["reserved_requests"],1)
    def test_git_cas(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"repo";root.mkdir()
            git(root,"init","-b","main")
            (root/"a.txt").write_text("old")
            git(root,"add","a.txt");git(root,"commit","-m","seed")
            baseline=inspect(root);p={"paths":["a.txt","new"]}
            s=Staging(root,p,"gexec-"+"a"*32,baseline,Path(d)/"journal");s.start()
            before=inventory(root,s.head(),p)
            edits=proposal(before,{"new/b.txt":b"new"},["a.txt","new/b.txt"])
            task={"id":"A","writes":["a.txt","new/b.txt"]}
            with self.assertRaises(ValueError):s.publish(task,1,edits,lambda d:[{"exit_code":1}])
            self.assertEqual(s.head(),baseline["head"])
            r=s.publish(task,1,edits,lambda data:[{"exit_code":0}])
            self.assertEqual(s.head(),r["new"]);self.assertEqual(inspect(root),baseline)
            self.assertEqual((root/"a.txt").read_text(),"old")
            self.assertEqual(inventory(root,s.head(),p),{"new/b.txt":b"new"})
            self.assertEqual(s.publish(task,1,edits,lambda d:(_ for _ in ()).throw(AssertionError())),r)
            # Missing post-CAS receipt is reconciled, not duplicated.
            next((Path(d)/"journal").glob("*.done.json")).unlink()
            self.assertEqual(s.publish(task,1,edits,lambda d:[]),r)
            self.assertEqual(len(list((Path(d)/"journal").glob("*.done.json"))),1)
            with self.assertRaises(ValueError):s.publish(task,2,edits,lambda d:[{"exit_code":0}])
    def test_mailbox_fence(self):
        p={"id":"m","task":"A","attempt":1,"sender":"W","recipient":"V","text":"contract","kind":"HANDOFF","correlation_id":None}
        self.assertTrue(valid_packet(p))
        self.assertFalse(valid_packet({**p,"attempt":True}))
        self.assertFalse(valid_packet({**p,"kind":"ANSWER"}))
        self.assertFalse(can_recover({"m":{"sender_generation":{"task":"A","attempt":1},"status":"PROCESSED"}},"A",1))
        self.assertTrue(can_recover({},"A",1))
