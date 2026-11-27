"""Typed, JSON-only live mailbox fields for deterministic Temporal replay."""
from __future__ import annotations
from typing import Literal,TypedDict

Kind=Literal["QUESTION","ANSWER","HANDOFF","PROGRESS","BLOCKED","CANCEL"]
class LivePacket(TypedDict):
    id:str
    task:str|None
    attempt:int|None
    sender:str
    recipient:str
    text:str
    kind:Kind
    correlation_id:str|None
class Generation(TypedDict):
    task:str|None
    attempt:int
class LiveEnvelope(TypedDict):
    packet:LivePacket
    sequence:int
    status:Literal["ACCEPTED","PROCESSED","EXPIRED","DEAD_LETTERED"]
    expires_at:str
    protocol_version:int
    sender_generation:Generation
    recipient_generation:Generation|None

def valid_packet(p):
    if type(p)!=dict or set(p)!={"id","task","attempt","sender","recipient","text","kind","correlation_id"}:return False
    if any(type(p[k])!=str or not p[k] for k in ("id","sender","recipient","text","kind")):return False
    if len(p["id"])>120 or len(p["text"].encode())>4096:return False
    if p["kind"] not in ("QUESTION","ANSWER","HANDOFF","PROGRESS","BLOCKED","CANCEL"):return False
    if p["correlation_id"] is not None and (type(p["correlation_id"])!=str or len(p["correlation_id"])>120):return False
    if p["kind"]=="ANSWER" and not p["correlation_id"]:return False
    if p["task"] is None:return p["attempt"] is None
    return type(p["task"])==str and type(p["attempt"])==int and p["attempt"]>=1

def generation(packet):
    return {"task":packet["task"],"attempt":packet["attempt"] if packet["task"] is not None else 1}

def can_recover(messages,task,attempt):
    # A published/processed outgoing message may have influenced peer work.
    # Do not replay a generation with an acknowledged outgoing effect.
    g={"task":task,"attempt":attempt}
    return not any(m.get("sender_generation")==g and m["status"]=="PROCESSED" for m in messages.values())
