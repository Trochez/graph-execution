import tempfile
import unittest
from pathlib import Path
from graph_execution_runtime.workspace import snapshot,integrate,sha,validate_proposal

class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.root=self.base/"work";self.root.mkdir()
        (self.root/"owned.txt").write_text("original")
        self.task={"id":"T","writes":["owned.txt"]}
    def tearDown(self):
        self.tmp.cleanup()
    def edit(self,name="owned.txt",content="new"):
        return {"path":name,"base":snapshot(self.root,name)[0],"content":content,"sha256":sha(content.encode())}
    def test_no_replay_and_no_stale_write(self):
        e=self.edit()
        r=integrate(self.root,self.base/"journal",self.task,1,[e])
        self.assertTrue(r["applied"])
        self.assertEqual((self.root/"owned.txt").read_text(),"new")
        with self.assertRaises(ValueError):validate_proposal(self.root,self.task,[e])
        with self.assertRaises(FileExistsError):
            integrate(self.root,self.base/"journal",self.task,1,[self.edit(content="other")])
        self.assertEqual((self.root/"owned.txt").read_text(),"new")
    def test_outside_scope_and_symlink(self):
        with self.assertRaises(ValueError):
            validate_proposal(self.root,self.task,[self.edit(name="unowned.txt")])
        outside=self.base/"outside.txt";outside.write_text("safe")
        (self.root/"linked.txt").symlink_to(outside)
        with self.assertRaises(ValueError):snapshot(self.root,"linked.txt")
        self.assertEqual(outside.read_text(),"safe")
    def test_reject_digest_mismatch(self):
        e=self.edit();e["sha256"]="0"*64
        with self.assertRaises(ValueError):validate_proposal(self.root,self.task,[e])
