"""Capability resolution, never infer an active host from PATH."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Mode:
    name: str
    required: frozenset[str]
    limitations: tuple[str, ...] = ()

MODES = {
    "codex-native": Mode("codex-native", frozenset({"spawn", "status", "wait", "model_override"})),
    "cline-team": Mode("cline-team", frozenset({"spawn", "status", "wait", "model_override", "message"})),
    "cline-subagent": Mode("cline-subagent", frozenset({"spawn", "model_override"}), ("persistent_peer_unverified",)),
    "pax-durable": Mode("pax-durable", frozenset({"bridge", "temporal", "model_override", "message", "status"}),
                        ("candidate", "trusted_local_namespace", "whole_turn_checkpoint")),
}

def select_mode(host: str, observed: dict[str, str], *, persistent_peers: bool = False) -> Mode:
    choices = {"codex": ["codex-native"], "cline": ["cline-team", "cline-subagent"], "pax": ["pax-durable"]}.get(host, [])
    for name in choices:
        mode = MODES[name]
        if persistent_peers and name == "cline-subagent":
            continue
        required = mode.required | ({"message"} if persistent_peers else set())
        if all(observed.get(key) == "supported" for key in required):
            return mode
    raise ValueError("CAPABILITY_UNAVAILABLE: active host or required live tools not established")
