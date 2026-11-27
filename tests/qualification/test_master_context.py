import copy,json,unittest
from graph_execution_runtime.master_context import preparation_context,proposal_for_master,verification_for_master

class MasterContextTests(unittest.TestCase):
    def test_prepare_catalog_only_once(self):
        argv=["python","-c","assert True # "+"x"*1500]
        p={"paths":["src"],"checks":[argv],"wheels":{},"capacity":1}
        tasks={"tasks":[{"id":"T","source":"plan","outcome":"new file","verification":"check","depends_on":[],"write_scope":["src/a.py"]}]}
        team={"agents":[{"id":"M","role":"master"},{"id":"W","role":"worker"}],
              "task_assignments":[{"task_id":"T","owner_agent_id":"W"}]}
        result=preparation_context(p,tasks,team,["src/a.py"])
        self.assertEqual(result["checks"],[argv])
        self.assertEqual(json.dumps(result).count(argv[2]),1)
        self.assertEqual(result["tasks"],tasks["tasks"])
        self.assertEqual(result["compiled_contract"]["owners"],{"T":"W"})
    def test_proposal_retains_all_edits_and_digest(self):
        cmd=["python","-c","assert True # "+"x"*1500]
        original={"attempt":1,"proposal_sha256":"a"*64,"edits":[{"path":"src/a.py","content":"x=1\n"*100}],"input_hashes":{"src/a.py":"b"*64},
            "commands":[{"argv":cmd,"exit_code":0,"output_sha256":"c"*64},{"argv":["python","-c","file operation","z"*1500],"exit_code":0}]}
        frozen=copy.deepcopy(original)
        projected=proposal_for_master(original,[cmd])
        self.assertEqual(original,frozen)
        self.assertEqual(projected["edits"],original["edits"])
        self.assertEqual(projected["proposal_sha256"],original["proposal_sha256"])
        self.assertEqual(projected["input_hashes"],original["input_hashes"])
        self.assertEqual(projected["commands"][0]["check_index"],0)
        self.assertEqual(projected["commands"][0]["output_sha256"],"c"*64)
        self.assertNotIn("argv",projected["commands"][1])
        self.assertLess(len(json.dumps(projected)),len(json.dumps(original))/2)
    def test_review_preserves_failed_exit_and_decision(self):
        cmd=["python","-c","assert False"]
        result={"accepted":True,"status":"blocked","verification":{"decision":{"accepted":True},"checks":[{"argv":cmd,"exit_code":1,"timeout":False}]}}
        r=verification_for_master(result,[cmd])
        self.assertEqual(r["status"],"blocked")
        self.assertEqual(r["verification"]["decision"],result["verification"]["decision"])
        self.assertEqual(r["verification"]["checks"][0]["exit_code"],1)
        self.assertEqual(r["verification"]["checks"][0]["check_index"],0)
