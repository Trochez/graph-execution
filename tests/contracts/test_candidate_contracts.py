import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from pydantic import ValidationError

from graph_execution_runtime.contracts import ArtifactRef
from graph_execution_runtime.messaging import Answer, Cancel, Mailbox, MessageDraft, Principal, Question


class ContractTests(unittest.TestCase):
    def test_path_escape_rejected(self):
        args = dict(artifact_id="a", sha256="0"*64, bytes=1, media_type="text/plain",
                    task_id="t", attempt_id="x", base_revision="0"*40, retention="run")
        for path in ("../secret", "/abs", "C:/abs", "a/../b", "a\\b"):
            with self.subTest(path=path), self.assertRaises(ValidationError):
                ArtifactRef(path=path, **args)
        self.assertEqual(ArtifactRef(path="a/b.txt", **args).path, "a/b.txt")

    def setUp(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.a = Principal(agent_id="a", generation=1)
        self.b = Principal(agent_id="b", generation=1)
        self.master = Principal(agent_id="master", generation=1)
        self.box = Mailbox("run", 1, "master", {"master": 1, "a": 1, "b": 1}, max_messages=2)

    def draft(self, payload=None, **kwargs):
        args = dict(message_id=uuid4(), recipient_id="b", conversation_id="c",
                    deadline=self.now + timedelta(seconds=30), payload=payload or Question(text="contract?"))
        args.update(kwargs)
        return MessageDraft(**args)

    def test_duplicate_and_lost_ack(self):
        d = self.draft()
        r = self.box.send(self.a, d, self.now)
        self.assertEqual(self.box.send(self.a, d, self.now), r)
        self.assertEqual(self.box.page(self.b, self.now), self.box.page(self.b, self.now))
        with self.assertRaises(PermissionError):
            self.box.acknowledge(self.a, d.message_id, self.now, processed=True)
        done = self.box.acknowledge(self.b, d.message_id, self.now, processed=True)
        self.assertEqual(done, self.box.acknowledge(self.b, d.message_id, self.now, processed=True))
        self.assertEqual(self.box.send(self.a, d, self.now), done)
        self.assertEqual(self.box.page(self.b, self.now), [])
        with self.assertRaises(ValueError):
            self.box.send(self.a, d.model_copy(update={"payload": Question(text="changed")}), self.now)

    def test_reply_requires_valid_correlation(self):
        d = self.draft()
        self.box.send(self.a, d, self.now)
        answer = self.draft(Answer(text="ok"), recipient_id="a", correlation_id=d.message_id)
        self.assertEqual(self.box.send(self.b, answer, self.now).status, "ACCEPTED")
        with self.assertRaises(ValueError):
            self.box.send(self.b, answer.model_copy(update={"message_id": uuid4(), "correlation_id": uuid4()}), self.now)

    def test_capacity_and_control_lane(self):
        self.box.send(self.a, self.draft(), self.now)
        self.box.send(self.a, self.draft(), self.now)
        with self.assertRaises(OverflowError):
            self.box.send(self.a, self.draft(), self.now)
        cancel = self.draft(Cancel(reason="stop"))
        with self.assertRaises(PermissionError):
            self.box.send(self.a, cancel, self.now)
        self.box.send(self.master, cancel, self.now)
        self.assertEqual(self.box.page(self.b, self.now)[0].draft.payload.kind, "CANCEL")

    def test_expired_and_stale(self):
        d = self.draft(recipient_generation=1)
        self.box.send(self.a, d, self.now)
        with self.assertRaises(PermissionError):
            self.box.page(Principal(agent_id="b", generation=2), self.now)
        later = self.now + timedelta(minutes=1)
        self.assertEqual(self.box.page(self.b, later), [])
        self.assertEqual(self.box.receipts[d.message_id].status, "EXPIRED")
        with self.assertRaises(ValueError):
            self.box.acknowledge(self.b, d.message_id, later, processed=True)


if __name__ == "__main__":
    unittest.main()
