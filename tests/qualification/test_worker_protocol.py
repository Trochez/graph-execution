import unittest
from graph_execution_runtime.worker_protocol import initial_context,PeerEvidence,handoff_pairs

class WorkerProtocolTests(unittest.TestCase):
    def test_initial_scope_and_bound(self):
        t={"reads":["a","large"],"writes":["new"]}
        self.assertEqual(initial_context(t,{"a":b"test","large":b"x"*4097,"secret":b"never"}),{"a":{"text":"test"},"large":{"omitted":True,"bytes":4097},"new":{"absent":True}})
    def test_required_direct_handoff(self):
        p={"required_peer_handoff":True,"required_parallel_roots":["src/a","src/b"]}
        a={"id":"A","owner":"W1","writes":["src/a"],"dependencies":[]}
        b={"id":"B","owner":"W2","writes":["src/b"],"dependencies":[]}
        spec={"tasks":{"A":a,"B":b}}
        self.assertEqual(len(handoff_pairs(p,spec)),1)
        sender=PeerEvidence(a,p,spec);receiver=PeerEvidence(b,p,spec)
        sender.record_send("M","HANDOFF","relay",{"accepted":True})
        self.assertIsNotNone(sender.missing())
        sender.record_send("W2","HANDOFF","direct",{"accepted":True})
        self.assertIsNone(sender.missing())
        receiver.record_ack("direct",True)
        self.assertIsNotNone(receiver.missing())
        receiver.observe([{"id":"relay","kind":"HANDOFF","sender":"M"},{"id":"direct","kind":"HANDOFF","sender":"W1"}])
        receiver.record_ack("relay",True);self.assertIsNotNone(receiver.missing())
        receiver.record_ack("direct",False);self.assertIsNotNone(receiver.missing())
        receiver.record_ack("direct",True);self.assertIsNone(receiver.missing())
