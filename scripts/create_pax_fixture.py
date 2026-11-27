"""Create a fresh independent Python qualification project and a tiny offline wheel."""
from __future__ import annotations
import argparse,base64,csv,hashlib,io,json,zipfile
from pathlib import Path
from graph_execution_runtime.gitstage import git
from graph_execution_runtime.policy import hash_file

def wheel(directory):
    name="gexec_fixture_units-1.0.0-py3-none-any.whl"
    files={"gexec_fixture_units/__init__.py":b'__version__="1.0.0"\ndef cents(value):\n    return int(value)\n',
           "gexec_fixture_units-1.0.0.dist-info/METADATA":b"Metadata-Version: 2.1\nName: gexec-fixture-units\nVersion: 1.0.0\n",
           "gexec_fixture_units-1.0.0.dist-info/WHEEL":b"Wheel-Version: 1.0\nGenerator: gexec-fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n"}
    out=io.StringIO();writer=csv.writer(out,lineterminator="\n")
    rec="gexec_fixture_units-1.0.0.dist-info/RECORD"
    for p,b in sorted(files.items()):writer.writerow([p,"sha256="+base64.urlsafe_b64encode(hashlib.sha256(b).digest()).decode().rstrip("="),len(b)])
    writer.writerow([rec,"",""]);files[rec]=out.getvalue().encode()
    with zipfile.ZipFile(directory/name,"w") as z:
        for p,b in sorted(files.items()):z.writestr(zipfile.ZipInfo(p,(2020,1,1,0,0,0)),b)
    return name

PLAN="""# Implement order totals CLI

Fix the existing quantity validation bug: zero or negative quantity must raise ValueError. Keep valid integer quantities working.
Create a new directory order_cli containing a JSON CLI module run by python -m order_cli. It must accept two integer arguments, quantity and unit price in cents, and print deterministic JSON containing quantity, unit_price_cents, total_cents, and contract_version. Invalid input must exit nonzero. Use gexec_fixture_units.cents for the total, and add the exact approved dependency gexec-fixture-units==1.0.0 to requirements.txt.
The validation worker must choose a nonempty contract version string in orderlib/validation.py (CONTRACT_VERSION). The CLI worker must obtain the agreed interface/version through an actual peer HANDOFF and acknowledge it, then use that contract. Do not write the validation worker's paths from the CLI task. Both workers should begin by running relevant real tests before modifying files. The validation worker must run the original quantity test, observe its failure, repair and rerun it. The CLI worker must explicitly call install_dependencies with the approved wheel and test its implementation. They can work independently and exchange the contract; the final integration must use the shared implementation.
Remove obsolete.txt as an authorized deletion. Use an independent read-only reviewer after implementation and integration. Run the approved independent checks; do not weaken or edit the existing tests.
Acceptance: quantity validation passes, CLI valid totals and invalid input behavior pass, offline dependency is used, old file is absent, source remains deterministic, final checks pass. The original branch must not be changed.
"""
ORACLE="""import json, subprocess, sys, unittest
from pathlib import Path
import gexec_fixture_units
from orderlib.validation import validate_quantity, CONTRACT_VERSION
class Acceptance(unittest.TestCase):
    def test_behavior(self):
        self.assertEqual(gexec_fixture_units.__version__,"1.0.0")
        self.assertEqual(validate_quantity(2),2)
        for q in (0,-1):
            with self.assertRaises(ValueError):validate_quantity(q)
        a=subprocess.run([sys.executable,"-m","order_cli","3","125"],capture_output=True,text=True)
        self.assertEqual(a.returncode,0,a.stderr)
        self.assertEqual(json.loads(a.stdout),{"quantity":3,"unit_price_cents":125,"total_cents":375,"contract_version":CONTRACT_VERSION})
        self.assertEqual(a.stdout,subprocess.check_output([sys.executable,"-m","order_cli","3","125"],text=True))
        self.assertNotEqual(subprocess.run([sys.executable,"-m","order_cli","0","125"],capture_output=True).returncode,0)
        self.assertFalse(Path("obsolete.txt").exists())
        self.assertTrue(Path("order_cli/__main__.py").is_file())
        self.assertIn("gexec-fixture-units==1.0.0",Path("requirements.txt").read_text())
if __name__=="__main__":unittest.main()
"""
def main():
    p=argparse.ArgumentParser();p.add_argument("--output",required=True,type=Path);p.add_argument("--image",required=True)
    p.add_argument("--base-url",required=True);p.add_argument("--model",required=True);p.add_argument("--approval",type=Path,default=Path.home()/".config/graph-execution/pax/model-policy.json")
    a=p.parse_args();out=a.output.resolve();out.mkdir(mode=0o700,parents=True,exist_ok=False)
    root=out/"project";root.mkdir();(root/"orderlib").mkdir();(root/"tests").mkdir()
    (root/"orderlib/__init__.py").write_text("")
    (root/"orderlib/validation.py").write_text("def validate_quantity(q):\n    if q < 0: raise ValueError('negative')\n    return q\n")
    (root/"tests/test_validation.py").write_text("import unittest\nfrom orderlib.validation import validate_quantity\nclass Validation(unittest.TestCase):\n    def test_positive(self): self.assertEqual(validate_quantity(2),2)\n    def test_zero(self):\n        with self.assertRaises(ValueError): validate_quantity(0)\n    def test_negative(self):\n        with self.assertRaises(ValueError): validate_quantity(-1)\n")
    (root/"requirements.txt").write_text("");(root/"obsolete.txt").write_text("obsolete")
    (root/"pyproject.toml").write_text('[project]\nname="order-demo"\nversion="0.1.0"\nrequires-python=">=3.12"\n')
    git(root,"init","-b","main");git(root,"add",".");git(root,"commit","-m","Independent fixture seed")
    (out/"PLAN.md").write_text(PLAN)
    wheels=out/"wheels";wheels.mkdir();name=wheel(wheels)
    oracle=out/"oracle";oracle.mkdir();(oracle/"verify.py").write_text(ORACLE)
    check1=["python","-m","unittest","discover","-s","tests","-p","test_validation.py"]
    check2=["python","-c","import ast; from pathlib import Path; ast.parse(Path('order_cli/__main__.py').read_text()); import gexec_fixture_units; assert gexec_fixture_units.__version__=='1.0.0'"]
    check3=["python","-c","from pathlib import Path; assert not Path('obsolete.txt').exists()"]
    profile={"schema":2,"workspace":str(root),"image":a.image,"wheelhouse":str(wheels),"wheels":{name:hash_file(wheels/name)},
             "paths":["orderlib","order_cli","tests","requirements.txt","obsolete.txt","pyproject.toml"],"write_paths":["orderlib","order_cli","requirements.txt","obsolete.txt","pyproject.toml"],"commands":["python"],"checks":[check1,check2,check3],
             "final_checks":[check1,["python","/oracle/verify.py"]],"required_parallel_roots":["orderlib/validation.py","order_cli"],"require_independent_review":True,"capacity":2,"timeout":1200,"acknowledge":"local-trusted-docker-offline",
             "model":a.model,"base_url":a.base_url,"approval":str(a.approval.resolve()),"skill_root":str(Path(__file__).resolve().parents[1]),
             "oracle":str(oracle),"oracle_files":{"verify.py":hash_file(oracle/"verify.py")}}
    (out/"profile.json").write_text(json.dumps(profile,indent=2));(out/"profile.json").chmod(0o600)
    print(json.dumps({"fixture":str(out),"profile":str(out/"profile.json"),"plan":str(out/"PLAN.md"),"workspace":str(root),
                      "seed":git(root,"rev-parse","HEAD").decode().strip(),"plan_sha256":hash_file(out/"PLAN.md"),"wheel_sha256":profile["wheels"][name],"oracle_sha256":profile["oracle_files"]["verify.py"]},indent=2))
if __name__=="__main__":main()
