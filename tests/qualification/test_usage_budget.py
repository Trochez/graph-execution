"""Credential-free tests for concurrent reservation and HTTP response settlement."""
import asyncio
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import httpx
from graph_execution_runtime.budget import Budget,BudgetError
from graph_execution_runtime.usage_capture import UsageStream

def body(n=10):
    return json.dumps({"max_tokens":4096,"messages":[{"content":"x"*n}]}).encode()
def usage(p=100,c=25):
    return {"prompt_tokens":p,"completion_tokens":c,"total_tokens":p+c}

class Chunks(httpx.AsyncByteStream):
    def __init__(self,parts):self.parts=parts;self.closed=False
    async def __aiter__(self):
        for part in self.parts:yield part
    async def aclose(self):self.closed=True

class UsageBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"budget.db"
        self.b=Budget(self.path,"master",60,"plan")
    def test_settle_once_and_recover_after_restart(self):
        rid=self.b.reserve(body());before=self.b.summary()["charged_tokens"]
        self.assertGreater(before,125)
        self.assertTrue(self.b.settle(rid,usage()))
        restarted=Budget(self.path,"master",60,"plan")
        self.assertTrue(restarted.settle(rid,usage()))
        self.assertFalse(restarted.settle(rid,usage(20,1)))
        self.assertEqual(restarted.summary()["charged_tokens"],125)
        self.assertEqual(restarted.summary()["settled_requests"],1)
    def test_invalid_or_missing_usage_retains_reservation(self):
        rid=self.b.reserve(body());before=self.b.summary()["charged_tokens"]
        for u in (None,{},usage(0,0),{"prompt_tokens":5,"completion_tokens":1,"total_tokens":2}):
            self.assertFalse(self.b.settle(rid,u))
        self.assertEqual(self.b.summary()["charged_tokens"],before)
        self.assertEqual(self.b.summary()["unsettled_requests"],1)
    def test_overreported_usage_never_hidden(self):
        rid=self.b.reserve(body());self.assertTrue(self.b.settle(rid,usage(20000,1)))
        self.assertEqual(self.b.summary()["charged_tokens"],20001)
        self.assertEqual(self.b.summary()["budget_rejections"][-1]["code"],"PROVIDER_USAGE_ABOVE_RESERVATION")
    def test_atomic_concurrent_admission_and_worker_headroom(self):
        def reserve(_):
            try:return self.b.reserve(body(59000))
            except BudgetError:return None
        with ThreadPoolExecutor(max_workers=8) as pool:rids=list(pool.map(reserve,range(20)))
        s=self.b.summary()
        self.assertEqual(s["reserved_requests"],sum(x is not None for x in rids))
        self.assertLessEqual(s["charged_tokens"],650000)
        self.assertTrue(any(r["code"]=="PLANNING_TOKEN_LIMIT" for r in s["budget_rejections"]))
        worker=Budget(self.path,"V",12)
        rid=worker.reserve(body(59000));self.assertTrue(worker.settle(rid,usage()))
        self.assertEqual(worker.summary()["requests_by_actor"]["V"],1)
    def test_http_hooks_nonstream_and_sse(self):
        async def run():
            normal=json.dumps({"usage":usage()}).encode()
            events=b'data: {"choices":[],"usage":'+json.dumps(usage(200,50)).encode()+b'}\n\ndata: [DONE]\n\n'
            async def handler(req):
                if req.headers.get("x-test-stream")=="yes":
                    return httpx.Response(200,headers={"content-type":"text/event-stream"},stream=Chunks([events[:19],events[19:60],events[60:]]))
                return httpx.Response(200,headers={"content-type":"application/json"},stream=Chunks([normal[:10],normal[10:]]))
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler),event_hooks={"request":[self.b.on_request],"response":[self.b.on_response]}) as client:
                r=await client.post("http://localhost/v1/chat/completions",content=body())
                self.assertEqual(r.content,normal)
                async with client.stream("POST","http://localhost/v1/chat/completions",content=body(),headers={"x-test-stream":"yes"}) as r:
                    self.assertEqual(await r.aread(),events)
            s=self.b.summary()
            self.assertEqual(s["settled_requests"],2)
            self.assertEqual(s["charged_tokens"],375)
        asyncio.run(run())
    def test_truncated_stream_is_not_settled(self):
        async def run():
            rid=self.b.reserve(body())
            raw=b'data: {"usage":'+json.dumps(usage()).encode()+b'}\n\n'
            stream=UsageStream(Chunks([raw]),self.b,rid,True)
            self.assertEqual(b"".join([x async for x in stream]),raw)
            await stream.aclose()
            self.assertEqual(self.b.summary()["unsettled_requests"],1)
        asyncio.run(run())
    def test_actor_request_limit_not_refunded(self):
        b=Budget(self.path,"V",1)
        b.settle(b.reserve(body()),usage())
        with self.assertRaises(BudgetError):b.reserve(body())
        self.assertEqual(b.summary()["budget_rejections"][-1]["code"],"ACTOR_REQUEST_LIMIT")
