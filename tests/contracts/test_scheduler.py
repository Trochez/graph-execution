import unittest
from graph_execution_runtime.scheduler import initialize, ready, validate_tasks, normalized
from graph_execution_runtime.registry import select_mode

def task(key, owner, deps=(), writes=(), reads=(), resources=()):
    return dict(id=key,owner=owner,dependencies=list(deps),writes=list(writes),reads=list(reads),resources=list(resources),checks=["verify"])

class SchedulerTests(unittest.TestCase):
    def test_fork_join_conflict_and_owner(self):
        tasks = {"a":task("a","a",writes=["src/a"]), "b":task("b","b",writes=["src/b"]),
                 "c":task("c","c",["a","b"],reads=["src/a","src/b"]),
                 "d":task("d","d",writes=["src"])}
        s=initialize(tasks)
        self.assertEqual(ready(tasks,s,2),["a","b"])
        s["a"]["status"]="verifying";s["b"]["status"]="done"
        self.assertEqual(ready(tasks,s,3),[])
        s["a"]["status"]="done"
        self.assertEqual(ready(tasks,s,3),["c"])
    def test_paths_and_cycles(self):
        for p in ["../a","/a","a//b","a/../b",".git/config","C:/file"]:
            with self.assertRaises(ValueError): normalized(p)
        with self.assertRaises(ValueError):
            validate_tasks({"a":task("a","w",["a"])},{"m":{"role":"master"},"w":{"role":"worker"}},"m")
    def test_unknown_or_peer_incapable(self):
        with self.assertRaises(ValueError): select_mode("unknown",{"spawn":"supported"})
        with self.assertRaises(ValueError):
            select_mode("cline",{"spawn":"supported","model_override":"supported"},persistent_peers=True)
        self.assertEqual(select_mode("cline",{"spawn":"supported","model_override":"supported"}).name,"cline-subagent")
