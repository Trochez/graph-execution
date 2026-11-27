"""Persistent conservative admission and provider-reported usage settlement."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path

TOTAL=1_500_000
MASTER_LIMIT=1_000_000
PLANNING_LIMIT=650_000
CONTEXT_BYTES=60_000

class BudgetError(RuntimeError):
    def __init__(self,code,message):
        super().__init__(message);self.code=code

def init(db):
    # Keep the legacy requests(actor,tokens) projection: tokens is the current
    # charge (actual reported usage or the outstanding conservative reservation).
    db.execute("CREATE TABLE IF NOT EXISTS requests(actor TEXT NOT NULL,tokens INTEGER NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS tools(actor TEXT NOT NULL)")
    db.execute("CREATE TABLE IF NOT EXISTS rejections(actor TEXT,code TEXT,body_bytes INTEGER)")
    db.execute("""CREATE TABLE IF NOT EXISTS accounting(
        request_id INTEGER PRIMARY KEY, phase TEXT, reserved INTEGER NOT NULL,
        prompt INTEGER, completion INTEGER, actual INTEGER)""")

class Budget:
    def __init__(self,path,actor,request_cap,phase=None):
        self.path=Path(path);self.actor=actor;self.request_cap=request_cap;self.phase=phase
    def rejected(self,code,body_bytes):
        with sqlite3.connect(self.path,timeout=10) as db:
            init(db)
            db.execute("INSERT INTO rejections VALUES (?,?,?)",(self.actor,code,body_bytes))
    def reserve(self,body):
        if len(body)>CONTEXT_BYTES:
            self.rejected("CONTEXT_BODY_LIMIT",len(body))
            raise BudgetError("CONTEXT_BODY_LIMIT","conservative input context budget exceeded")
        request=json.loads(body)
        output=request.get("max_completion_tokens",request.get("max_tokens"))
        if type(output)!=int or not 1<=output<=8192:
            self.rejected("OUTPUT_LIMIT",len(body))
            raise BudgetError("OUTPUT_LIMIT","bounded output reservation required")
        tokens=len(body)+4096+output
        code=None
        with sqlite3.connect(self.path,timeout=10) as db:
            init(db);db.execute("BEGIN IMMEDIATE")
            count,total=db.execute("SELECT count(*),coalesce(sum(tokens),0) FROM requests").fetchone()
            own,own_tokens=db.execute("SELECT count(*),coalesce(sum(tokens),0) FROM requests WHERE actor=?",(self.actor,)).fetchone()
            if count>=120:code="GLOBAL_REQUEST_LIMIT"
            elif own>=self.request_cap:code="ACTOR_REQUEST_LIMIT"
            elif total+tokens>TOTAL:code="GLOBAL_TOKEN_LIMIT"
            elif self.actor=="master" and self.phase and own_tokens+tokens>MASTER_LIMIT:code="MASTER_TOKEN_LIMIT"
            elif self.actor=="master" and self.phase in ("plan","team","prepare"):
                planning=db.execute("""SELECT coalesce(sum(r.tokens),0) FROM requests r
                    JOIN accounting a ON a.request_id=r.rowid
                    WHERE r.actor='master' AND a.phase IN ('plan','team','prepare')""").fetchone()[0]
                if planning+tokens>PLANNING_LIMIT:code="PLANNING_TOKEN_LIMIT"
            if code:
                db.execute("INSERT INTO rejections VALUES (?,?,?)",(self.actor,code,len(body)))
            else:
                rid=db.execute("INSERT INTO requests VALUES (?,?)",(self.actor,tokens)).lastrowid
                db.execute("INSERT INTO accounting(request_id,phase,reserved) VALUES (?,?,?)",(rid,self.phase,tokens))
        if code:raise BudgetError(code,"durable provider budget exhausted: "+code)
        return rid
    def settle(self,rid,usage):
        """Settle exactly once from a completed successful provider response.
        Missing or inconsistent usage leaves the original reservation charged.
        No estimates are substituted for reported counts.
        """
        if not isinstance(usage,dict):return False
        p,c,t=(usage.get(k) for k in ("prompt_tokens","completion_tokens","total_tokens"))
        if any(type(v)!=int or v<0 for v in (p,c,t)) or p<=0 or t!=p+c:return False
        with sqlite3.connect(self.path,timeout=10) as db:
            init(db);db.execute("BEGIN IMMEDIATE")
            row=db.execute("""SELECT a.actual,r.actor,a.reserved FROM accounting a
                JOIN requests r ON r.rowid=a.request_id WHERE a.request_id=?""",(rid,)).fetchone()
            if not row or row[1]!=self.actor:return False
            if row[0] is not None:return row[0]==t
            # Charge actual even if a provider reports more than reserved; never
            # hide excess usage. Subsequent admission is then fail-closed.
            db.execute("UPDATE accounting SET prompt=?,completion=?,actual=? WHERE request_id=?",(p,c,t,rid))
            db.execute("UPDATE requests SET tokens=? WHERE rowid=?",(t,rid))
            if t>row[2]:
                db.execute("INSERT INTO rejections VALUES (?,?,?)",(self.actor,"PROVIDER_USAGE_ABOVE_RESERVATION",0))
        return True
    async def on_request(self,request):
        if request.method=="POST" and request.url.path.rstrip("/").endswith("/chat/completions"):
            request.extensions["gexec_budget_id"]=self.reserve(request.content)
            # Read the wire format without changing the body or model route.
            request.headers["accept-encoding"]="identity"
    async def on_response(self,response):
        rid=response.request.extensions.get("gexec_budget_id")
        if rid is None or not response.is_success:return
        if response.headers.get("content-encoding","identity").lower() not in ("","identity"):return
        from .usage_capture import UsageStream,usage_from_json
        if response.is_stream_consumed:
            self.settle(rid,usage_from_json(response.content))
        else:
            response.stream=UsageStream(response.stream,self,rid,
                "text/event-stream" in response.headers.get("content-type","").lower())
    def tool(self):
        with sqlite3.connect(self.path,timeout=10) as db:
            init(db);db.execute("BEGIN IMMEDIATE")
            total=db.execute("SELECT count(*) FROM tools").fetchone()[0]
            own=db.execute("SELECT count(*) FROM tools WHERE actor=?",(self.actor,)).fetchone()[0]
            if total>=240 or (self.actor!="master" and own>=60):raise RuntimeError("durable tool budget exhausted")
            db.execute("INSERT INTO tools VALUES (?)",(self.actor,))
    def summary(self):
        with sqlite3.connect(self.path,timeout=10) as db:
            init(db)
            n,t=db.execute("SELECT count(*),coalesce(sum(tokens),0) FROM requests").fetchone()
            tools=db.execute("SELECT count(*) FROM tools").fetchone()[0]
            settled,p,c,actual=db.execute("SELECT count(actual),coalesce(sum(prompt),0),coalesce(sum(completion),0),coalesce(sum(actual),0) FROM accounting").fetchone()
            rejected=[{"actor":a,"code":code,"body_bytes":b} for a,code,b in db.execute("SELECT actor,code,body_bytes FROM rejections")]
            return {"reserved_requests":n,"conservative_reserved_tokens":t,"charged_tokens":t,
                "provider_reported_tokens":actual,"provider_reported_input_tokens":p,"provider_reported_output_tokens":c,
                "settled_requests":settled,"unsettled_requests":n-settled,"unsettled_reserved_tokens":t-actual,
                "counted_bridge_and_worker_tools":tools,
                "context_rejections":[r for r in rejected if r["code"]=="CONTEXT_BODY_LIMIT"],
                "budget_rejections":rejected,
                "requests_by_actor":dict(db.execute("SELECT actor,count(*) FROM requests GROUP BY actor").fetchall()),
                "charged_by_actor":dict(db.execute("SELECT actor,sum(tokens) FROM requests GROUP BY actor").fetchall()),
                "charged_by_phase":dict(db.execute("""SELECT coalesce(a.phase,'worker_or_legacy'),sum(r.tokens)
                    FROM requests r LEFT JOIN accounting a ON a.request_id=r.rowid GROUP BY 1""").fetchall())}
