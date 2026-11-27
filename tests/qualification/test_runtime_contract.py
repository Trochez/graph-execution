"""Regression for real L01 team assigning integration I to master M."""
import copy
import unittest
from graph_execution_runtime.runtime_contract import team_contract,extension_contract,RuntimeContractError

class RuntimeTeamContractTests(unittest.TestCase):
    def setUp(self):
        self.rows=[{"id":"V","write_scope":["orderlib/validation.py"]},{"id":"C","write_scope":["order_cli","requirements.txt"]},{"id":"I","write_scope":["obsolete.txt"]},{"id":"R","write_scope":[]}]
        self.team={"agents":[{"id":"M","role":"master","reports_to":None},{"id":"W1","role":"worker","reports_to":"M"},{"id":"W2","role":"worker","reports_to":"M"},{"id":"W3","role":"reviewer","reports_to":"M"}],
                   "task_assignments":[{"task_id":k,"owner_agent_id":o} for k,o in [("V","W1"),("C","W2"),("I","M"),("R","W3")]]}
        self.profile={"paths":["orderlib","order_cli","requirements.txt","obsolete.txt"],"checks":[["python","-m","unittest"]]}
    def assert_code(self,code,fn):
        with self.assertRaises(RuntimeContractError) as ctx:fn()
        self.assertEqual(ctx.exception.code,code)
    def corrected(self):
        t=copy.deepcopy(self.team);t["task_assignments"][2]["owner_agent_id"]="W1";return t
    def ext(self):
        return {"master":"M","roles":{a["id"]:a["role"] for a in self.team["agents"]},"parents":{a["id"]:a["reports_to"] for a in self.team["agents"]},
                "scopes":{r["id"]:{"reads":[],"writes":[],"resources":[],"checks":self.profile["checks"]} for r in self.rows}}
    def test_master_integration_rejected(self):
        self.assert_code("MASTER_TASK_OWNER",lambda:team_contract(self.rows,self.team))
        self.assertEqual(team_contract(self.rows,self.corrected())[3]["I"],"W1")
    def test_compile_uses_same_ownership(self):
        self.assert_code("MASTER_TASK_OWNER",lambda:extension_contract(self.profile,{"tasks":self.rows},self.team,self.ext()))
        extension_contract(self.profile,{"tasks":self.rows},self.corrected(),self.ext())
    def test_role_and_parent_drift(self):
        ext=self.ext();ext["roles"]["W3"]="worker"
        self.assert_code("ROLE_DRIFT",lambda:extension_contract(self.profile,{"tasks":self.rows},self.corrected(),ext))
        ext=self.ext();ext["parents"]["W1"]="W2"
        self.assert_code("PARENT_DRIFT",lambda:extension_contract(self.profile,{"tasks":self.rows},self.corrected(),ext))
    def test_reviewer_write_rejected(self):
        t=self.corrected();t["task_assignments"][2]["owner_agent_id"]="W3"
        self.assert_code("REVIEWER_WRITES",lambda:team_contract(self.rows,t))
    def test_scope_and_check_feedback(self):
        ext=self.ext();ext["scopes"]["I"]["writes"]=["outside.py"]
        self.assert_code("SCOPE_NOT_APPROVED",lambda:extension_contract(self.profile,{"tasks":self.rows},self.corrected(),ext))
        ext=self.ext();ext["scopes"]["I"]["checks"]=[["python","-c","print(1)"]]
        self.assert_code("CHECK_NOT_APPROVED",lambda:extension_contract(self.profile,{"tasks":self.rows},self.corrected(),ext))
