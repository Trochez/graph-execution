"""Regressions for source-plan detail loss and a syntax-only CLI false positive."""
import importlib.util,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from graph_execution_runtime.worker_protocol import plan_slice
from graph_execution_runtime.policy import command,validate_required_checks,required_check_indices
from graph_execution_runtime.scope_compiler import normalize_extension
from graph_execution_runtime.runtime_contract import RuntimeContractError

spec=importlib.util.spec_from_file_location("qualification_fixture",Path(__file__).resolve().parents[2]/"scripts/create_pax_fixture.py")
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)

class RequirementsTests(unittest.TestCase):
    def test_exact_original_plan_reaches_worker(self):
        p=plan_slice(fixture.PLAN)
        self.assertTrue(p["complete"])
        self.assertEqual(p["text"],fixture.PLAN)
        self.assertIn("unit_price_cents",p["text"])
        self.assertIn("contract_version",p["text"])
    def test_plan_pagination_preserves_unicode(self):
        text="😀 x"*4000;parts=[];offset=0
        while offset is not None:
            p=plan_slice(text,offset);parts.append(p["text"])
            self.assertLessEqual(len(p["text"].encode()),6000)
            offset=p["next_offset"]
        self.assertEqual("".join(parts),text)
    def test_mandatory_checks_cannot_be_omitted(self):
        p={"paths":["src"],"checks":[["python","-c","assert True"],["python","-c","assert False"]],
           "required_checks_by_write_group":{"src":[1]}}
        validate_required_checks(p)
        tasks={"tasks":[{"id":"T","write_scope":["src"]}]}
        team={"agents":[{"id":"M","role":"master"},{"id":"W","role":"worker"}],
              "task_assignments":[{"task_id":"T","owner_agent_id":"W"}]}
        ext,receipt=normalize_extension(p,tasks,team,{"scopes":{"T":{"reads":[],"writes":["src/x.py"],"check_indices":[0]}}})
        self.assertEqual(ext["scopes"]["T"]["checks"],p["checks"])
        self.assertEqual(receipt["added_required_checks"],[{"task":"T","indices":[1]}])
        ext["scopes"]["T"]["checks"]=[p["checks"][0]]
        with self.assertRaises(RuntimeContractError):normalize_extension(p,tasks,team,ext)
        self.assertEqual(required_check_indices(p,["elsewhere.py"]),[])
    def test_invalid_required_mapping(self):
        p={"paths":["src"],"checks":[["python","-c","assert True"]],"required_checks_by_write_group":{"outside":[0]}}
        with self.assertRaises(ValueError):validate_required_checks(p)
    def test_behavioral_check_rejects_prior_incomplete_cli(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/"orderlib").mkdir();(root/"orderlib/__init__.py").write_text("")
            (root/"orderlib/validation.py").write_text("raise RuntimeError('parallel root not ready')")
            (root/"order_cli").mkdir();(root/"requirements.txt").write_text("gexec-fixture-units==1.0.0\n")
            wheels=root/"wheels";wheels.mkdir();name=fixture.wheel(wheels)
            argv=command(["python","-c",fixture.CLI_COMPONENT_CHECK],["python"])
            env=dict(os.environ,PYTHONPATH=str(wheels/name),PYTHONDONTWRITEBYTECODE="1")
            cli=root/"order_cli/__main__.py"
            cli.write_text("import argparse,json\nfrom gexec_fixture_units import cents\nfrom orderlib.validation import validate_quantity\np=argparse.ArgumentParser();p.add_argument('quantity',type=int);a=p.parse_args();q=validate_quantity(a.quantity);print(json.dumps(dict(quantity=q,total_cents=cents(q))))\n")
            def run():return subprocess.run([sys.executable,*argv[1:]],cwd=root,env=env,capture_output=True,text=True,timeout=10)
            self.assertNotEqual(run().returncode,0)
            cli.write_text("import argparse,json\nfrom gexec_fixture_units import cents\nfrom orderlib.validation import validate_quantity,CONTRACT_VERSION\np=argparse.ArgumentParser();p.add_argument('quantity',type=int);p.add_argument('price',type=int);a=p.parse_args()\ntry:q=validate_quantity(a.quantity)\nexcept ValueError as e:p.error(str(e))\nprint(json.dumps(dict(quantity=q,unit_price_cents=a.price,total_cents=cents(q*a.price),contract_version=CONTRACT_VERSION),sort_keys=True))\n")
            good=run()
            self.assertEqual(good.returncode,0,good.stderr)
            self.assertIn("CLI_COMPONENT_PASS",good.stdout)
            cli.write_text(cli.read_text().replace("contract_version=CONTRACT_VERSION","contract_version='component-vA'"))
            self.assertNotEqual(run().returncode,0)
            self.assertEqual((root/"orderlib/validation.py").read_text(),"raise RuntimeError('parallel root not ready')")
