import asyncio,json,sys,tempfile,unittest
from pathlib import Path
from graph_execution_runtime.process_control import matching_run,read_terminal,recover_receipt,stop_owned_process

class ProcessControlTests(unittest.TestCase):
    def test_abnormal_exit_recovers_no_go_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/("gexec-"+"a"*32);run.mkdir()
            identity={"run_id":run.name,"workspace":str(root/"project"),"original_plan":str(root/"PLAN.md")}
            (run/"run-identity.json").write_text(json.dumps(identity))
            record={"run_id":run.name,"records":str(run),"decision":"NO_GO","budget":{"requests":7}}
            (run/"FINAL_DECISION.json").write_text(json.dumps(record))
            self.assertEqual(matching_run(root,root/"project",root/"PLAN.md"),run)
            self.assertIsNone(matching_run(root,root/"other",root/"PLAN.md"))
            stdout=root/"stdout";stdout.write_text("")
            r,e=recover_receipt(stdout,run,-15,True)
            self.assertEqual(r["budget"],{"requests":7})
            self.assertEqual(r["run_id"],run.name)
            self.assertTrue(e["terminal_recovered"])
            self.assertFalse(e["stdout_matches_terminal"])
    def test_go_requires_matching_receipt_and_clean_exit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run=root/("gexec-"+"b"*32);run.mkdir()
            record={"run_id":run.name,"records":str(run),"decision":"GO"}
            (run/"FINAL_DECISION.json").write_text(json.dumps(record))
            stdout=root/"stdout";stdout.write_text(json.dumps(record))
            self.assertEqual(recover_receipt(stdout,run,0)[0]["decision"],"GO")
            self.assertEqual(recover_receipt(stdout,run,-15)[0]["decision"],"NO_GO")
            self.assertEqual(recover_receipt(stdout,run,0,True)[0]["decision"],"NO_GO")
            stdout.write_text("{}")
            self.assertEqual(recover_receipt(stdout,run,0)[0]["decision"],"NO_GO")
    def test_owned_process_shutdown(self):
        async def run():
            proc=await asyncio.create_subprocess_exec(sys.executable,"-c","import time;time.sleep(60)",start_new_session=True)
            await stop_owned_process(proc,grace=.1)
            self.assertIsNotNone(proc.returncode)
        asyncio.run(run())
