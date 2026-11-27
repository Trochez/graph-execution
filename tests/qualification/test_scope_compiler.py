"""Regression reproducing VAL/CLI/DELETE competing roots from live L01."""
import copy
import tempfile
from pathlib import Path
import unittest
from graph_execution_runtime.scope_compiler import normalize_extension,root_priorities
from graph_execution_runtime.runtime_contract import RuntimeContractError
from graph_execution_runtime.scheduler import ready,initialize
from graph_execution_runtime.parallel_contract import check_spec,ParallelContractError

class ScopeCompilerTests(unittest.TestCase):
    def setUp(self):
        self.profile={"paths":["orderlib","order_cli","obsolete.txt","tests"],"checks":[["python","-c","assert True"],["python","-m","unittest"]],
            "required_parallel_roots":["orderlib/validation.py","order_cli"],"required_peer_handoff":True,"capacity":2}
        self.rows=[{"id":"VAL","depends_on":[],"write_scope":["orderlib/validation.py"]},{"id":"CLI","depends_on":[],"write_scope":["order_cli"]},
                   {"id":"AAA_DELETE","depends_on":[],"write_scope":["obsolete.txt"]},{"id":"INTEGRATE","depends_on":["VAL","CLI","AAA_DELETE"],"write_scope":[]}]
        self.tasks={"tasks":self.rows}
        self.owners={"VAL":"A","CLI":"B","AAA_DELETE":"A","INTEGRATE":"B"}
        self.team={"agents":[{"id":"M","role":"master"},{"id":"A","role":"worker"},{"id":"B","role":"worker"}],
                   "task_assignments":[{"task_id":k,"owner_agent_id":v} for k,v in self.owners.items()],
                   "schedule":[{"task_id":k,"agent_id":v,"resources":[k]} for k,v in self.owners.items()]}
        self.compact={"scopes":{"VAL":{"reads":["tests/test.py"],"writes":["orderlib/validation.py"],"check_indices":[1]},
                               "CLI":{"reads":["orderlib/validation.py"],"writes":["order_cli/__main__.py"],"check_indices":[0]},
                               "AAA_DELETE":{"reads":[],"writes":["obsolete.txt"],"check_indices":[0]},
                               "INTEGRATE":{"reads":["orderlib/validation.py","order_cli/__main__.py"],"writes":[],"check_indices":[0,1]}}}
    def compile(self):
        ext,record=normalize_extension(self.profile,self.tasks,self.team,self.compact)
        priorities=root_priorities(self.profile,self.tasks,self.team,ext["scopes"])
        tasks={t["id"]:{"id":t["id"],"owner":self.owners[t["id"]],"dependencies":t["depends_on"],"priority":priorities.get(t["id"],0),**ext["scopes"][t["id"]]} for t in self.rows}
        spec={"tasks":tasks,"agents":{a["id"]:a for a in self.team["agents"]}}
        return ext,record,spec
    def test_live_overlap_and_priority(self):
        ext,record,spec=self.compile()
        self.assertEqual(ext["scopes"]["CLI"]["reads"],[])
        self.assertEqual(record["narrowed_peer_reads"],[{"task":"CLI","path":"orderlib/validation.py","reason":"required_direct_peer_handoff"}])
        self.assertEqual(ext["scopes"]["INTEGRATE"]["reads"],["orderlib/validation.py","order_cli/__main__.py"])
        self.assertEqual(ext["scopes"]["CLI"]["resources"],["CLI"])
        self.assertEqual(ext["parents"],{"M":None,"A":"M","B":"M"})
        self.assertEqual(set(ready(spec["tasks"],initialize(spec["tasks"]),2)),{"VAL","CLI"})
        check_spec(self.profile,spec)
    def test_shared_resource_not_dropped(self):
        self.team["schedule"][0]["resources"]=["shared"]
        self.team["schedule"][1]["resources"]=["shared"]
        ext,_,spec=self.compile()
        self.assertEqual(ext["scopes"]["CLI"]["resources"],["shared"])
        with self.assertRaisesRegex(ParallelContractError,"shared frozen resource"):check_spec(self.profile,spec)
    def test_no_handoff_no_narrowing(self):
        self.profile["required_peer_handoff"]=False
        ext,record,spec=self.compile()
        self.assertEqual(ext["scopes"]["CLI"]["reads"],["orderlib/validation.py"])
        self.assertEqual(record["narrowed_peer_reads"],[])
        with self.assertRaises(ParallelContractError):check_spec(self.profile,spec)
    def test_no_write_scope_expansion(self):
        self.compact["scopes"]["INTEGRATE"]["writes"]=["obsolete.txt"]
        with self.assertRaisesRegex(RuntimeContractError,"read-only tasks"):self.compile()
    def test_unapproved_read_cannot_be_laundered(self):
        self.compact["scopes"]["CLI"]["reads"].append("secrets.txt")
        with self.assertRaises(RuntimeContractError):self.compile()

    def test_live_directory_alias_resolves_to_exact_module(self):
        self.profile["directory_files"]={"order_cli":["order_cli/__main__.py"]}
        self.compact["scopes"]["CLI"]["writes"]=["order_cli"]
        self.compact["scopes"]["INTEGRATE"]["reads"]=["orderlib/validation.py","order_cli"]
        ext,record,spec=self.compile()
        self.assertEqual(ext["scopes"]["CLI"]["writes"],["order_cli/__main__.py"])
        self.assertEqual(ext["scopes"]["INTEGRATE"]["reads"],["orderlib/validation.py","order_cli/__main__.py"])
        self.assertEqual(record["resolved_directories"],[
            {"task":"CLI","field":"writes","directory":"order_cli","files":["order_cli/__main__.py"]},
            {"task":"INTEGRATE","field":"reads","directory":"order_cli","files":["order_cli/__main__.py"]}])
        check_spec(self.profile,spec)
    def test_undeclared_directory_child_rejected(self):
        self.profile["directory_files"]={"order_cli":["order_cli/__main__.py"]}
        self.compact["scopes"]["CLI"]["writes"]=["order_cli/other.py"]
        with self.assertRaises(RuntimeContractError) as ctx:self.compile()
        self.assertEqual(ctx.exception.code,"EXACT_FILE_REQUIRED")
    def test_full_extension_cannot_treat_directory_as_file(self):
        self.profile["directory_files"]={"order_cli":["order_cli/__main__.py"]}
        ext,_,_=self.compile()
        ext["scopes"]["CLI"]["writes"]=["order_cli"]
        with self.assertRaises(RuntimeContractError) as ctx:normalize_extension(self.profile,self.tasks,self.team,ext)
        self.assertEqual(ctx.exception.code,"EXACT_FILE_REQUIRED")
    def test_unmapped_existing_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/"order_cli").mkdir()
            self.profile["workspace"]=d
            self.compact["scopes"]["CLI"]["writes"]=["order_cli"]
            with self.assertRaises(RuntimeContractError) as ctx:self.compile()
            self.assertEqual(ctx.exception.code,"EXACT_FILE_REQUIRED")
    def test_mapping_cannot_escape_declared_group(self):
        self.profile["directory_files"]={"order_cli":["obsolete.txt"]}
        with self.assertRaises(ValueError):self.compile()
