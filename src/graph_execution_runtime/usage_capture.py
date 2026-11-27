"""Observe successful HTTPX response bodies without buffering or changing delivery."""
from __future__ import annotations
import json
import httpx

MAX_CAPTURE=1_048_576

def usage_from_json(raw):
    try:
        value=json.loads(raw)
        return value.get("usage") if isinstance(value,dict) and not value.get("error") else None
    except (ValueError,UnicodeError):return None

class UsageStream(httpx.AsyncByteStream):
    def __init__(self,inner,budget,rid,sse):
        self.inner=inner;self.budget=budget;self.rid=rid;self.sse=sse
        self.buf=b"";self.usage=None;self.disabled=False;self.done=False;self.error=False
    def feed(self,chunk):
        if self.disabled or self.done:return
        if len(self.buf)+len(chunk)>MAX_CAPTURE:
            self.disabled=True;self.buf=b"";return
        self.buf+=chunk
        if not self.sse:return
        while b"\n" in self.buf:
            line,self.buf=self.buf.split(b"\n",1)
            if not line.startswith(b"data:"):continue
            data=line[5:].strip()
            if data==b"[DONE]":
                self.done=True
                if not self.error and self.usage is not None:self.budget.settle(self.rid,self.usage)
                return
            try:obj=json.loads(data)
            except (ValueError,UnicodeError):continue
            if isinstance(obj,dict):
                if obj.get("error"):self.error=True
                if isinstance(obj.get("usage"),dict):self.usage=obj["usage"]
    async def __aiter__(self):
        # A truncated/abandoned stream keeps the full reservation. A final
        # SSE [DONE] is recognized before yielding it, as clients may stop there.
        async for chunk in self.inner:
            self.feed(chunk)
            yield chunk
        if not self.disabled and not self.sse:
            self.budget.settle(self.rid,usage_from_json(self.buf))
        self.buf=b""
    async def aclose(self):
        self.buf=b""
        await self.inner.aclose()
