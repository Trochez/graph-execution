"""Conservative persistent request/token reservations shared by all live processes."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

class Budget:
    def __init__(self,path,actor,request_cap):
        self.path=Path(path);self.actor=actor;self.request_cap=request_cap
    def reserve(self,body):
        if len(body)>60000:raise RuntimeError("conservative input context budget exceeded")
        request=json.loads(body)
        output=request.get("max_completion_tokens",request.get("max_tokens"))
        if type(output)!=int or not 1<=output<=8192:raise RuntimeError("bounded output reservation required")
        # Bytes plus fixed overhead is deliberately conservative, not measured tokens.
        tokens=len(body)+4096+output
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests(actor TEXT NOT NULL,tokens INTEGER NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            count,total=db.execute("SELECT count(*),coalesce(sum(tokens),0) FROM requests").fetchone()
            own=db.execute("SELECT count(*) FROM requests WHERE actor=?",(self.actor,)).fetchone()[0]
            if count>=120 or own>=self.request_cap or total+tokens>1500000:raise RuntimeError("durable provider budget exhausted")
            db.execute("INSERT INTO requests VALUES (?,?)",(self.actor,tokens))
    async def on_request(self,request):
        if request.method=="POST" and request.url.path.rstrip("/").endswith("/chat/completions"):
            self.reserve(request.content)
    def tool(self):
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute("CREATE TABLE IF NOT EXISTS tools(actor TEXT NOT NULL)")
            db.execute("BEGIN IMMEDIATE")
            total=db.execute("SELECT count(*) FROM tools").fetchone()[0]
            own=db.execute("SELECT count(*) FROM tools WHERE actor=?",(self.actor,)).fetchone()[0]
            if total>=240 or (self.actor!="master" and own>=60):raise RuntimeError("durable tool budget exhausted")
            db.execute("INSERT INTO tools VALUES (?)",(self.actor,))
    def summary(self):
        with sqlite3.connect(self.path,timeout=10) as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests(actor TEXT NOT NULL,tokens INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS tools(actor TEXT NOT NULL)")
            n,t=db.execute("SELECT count(*),coalesce(sum(tokens),0) FROM requests").fetchone()
            tools=db.execute("SELECT count(*) FROM tools").fetchone()[0]
            return {"reserved_requests":n,"conservative_reserved_tokens":t,"counted_bridge_and_worker_tools":tools,
                    "requests_by_actor":dict(db.execute("SELECT actor,count(*) FROM requests GROUP BY actor").fetchall())}
