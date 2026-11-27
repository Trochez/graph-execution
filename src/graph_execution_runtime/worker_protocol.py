"""Bounded initial input context and explicit peer handoff evidence."""
from __future__ import annotations
from .scheduler import conflicts

def plan_slice(text,offset=0):
    """Bounded exact source text, with explicit continuation (character offset)."""
    if type(offset)!=int or not 0<=offset<=len(text):raise ValueError("invalid plan offset")
    end=min(len(text),offset+4000)
    while len(text[offset:end].encode("utf-8"))>6000:end-=1
    return {"text":text[offset:end],"offset":offset,"next_offset":end if end<len(text) else None,"complete":offset==0 and end==len(text),"total_characters":len(text)}

def initial_context(task,before,limit=12000):
    result={};remaining=limit
    for path in sorted(set(task["reads"]+task["writes"])):
        value=before.get(path)
        if value is None:result[path]={"absent":True};continue
        if len(value)>4096 or len(value)>remaining:
            result[path]={"omitted":True,"bytes":len(value)};continue
        result[path]={"text":value.decode("utf-8")}
        remaining-=len(value)
    return result

def handoff_pairs(profile,spec):
    if not profile.get("required_peer_handoff"):return []
    pair=profile["required_parallel_roots"]
    roots=[t for t in spec["tasks"].values() if not t["dependencies"]]
    return [(a,b) for a in roots for b in roots if a["id"]!=b["id"] and a["owner"]!=b["owner"]
            and any(conflicts(p,pair[0]) for p in a["writes"]) and any(conflicts(p,pair[1]) for p in b["writes"])]

class PeerEvidence:
    def __init__(self,task,profile,spec):
        self.sender=None;self.receiver=None;self.sent=set();self.observed={};self.acked=set()
        for a,b in handoff_pairs(profile,spec):
            if task["id"]==a["id"]:self.receiver=b["owner"]
            if task["id"]==b["id"]:self.sender=a["owner"]
    def requirement(self):
        if self.receiver:return {"send_handoff_to":self.receiver}
        if self.sender:return {"receive_and_ack_handoff_from":self.sender}
        return {}
    def record_send(self,recipient,kind,mid,receipt):
        if receipt.get("accepted") and kind=="HANDOFF" and recipient==self.receiver:self.sent.add(mid)
    def observe(self,packets):
        for p in packets:self.observed[p["id"]]=p
    def record_ack(self,mid,ok):
        p=self.observed.get(mid)
        if ok and p and p.get("kind")=="HANDOFF" and p.get("sender")==self.sender:self.acked.add(mid)
    def missing(self):
        if self.receiver and not self.sent:return "Send the agreed interface/version directly to the designated peer as HANDOFF before submitting."
        if self.sender and not self.acked:return "Receive the designated peer's HANDOFF, process it and explicitly acknowledge its message ID before submitting."
        return None
    def facts(self):
        return {"sent_handoffs":sorted(self.sent),"acknowledged_handoffs":sorted(self.acked)}
