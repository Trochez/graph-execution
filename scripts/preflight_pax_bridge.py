"""Custom Pax Agent seam probe. Offline master model; optional explicit real peer model.

Set GEXEC_PROBE_RECEIPT to a NEW output file outside the repository.
Never auto-trust a project, modify Pax settings, or install a global plugin.
"""
import json
import os
from pathlib import Path

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from preflight_harness_peer import build_live_model, execute_probe, skills

# Deliberately no file/shell tools and no fallback. Actual Pax TUI launches
# this agent via its documented --agent module:attribute interface.
agent = Agent(TestModel(call_tools=["run_peer_probe"], custom_output_text="GEXEC_BRIDGE_FINISHED"),
              capabilities=[skills()], instructions="Call run_peer_probe once; do not load or execute skills.")
called = False


@agent.tool_plain
async def run_peer_probe() -> str:
    """Run the bounded two-agent Temporal peer qualification, once."""
    global called
    if called:
        raise RuntimeError("probe already called")
    called = True
    path = Path(os.environ["GEXEC_PROBE_RECEIPT"]).expanduser().resolve()
    if path.exists():
        raise RuntimeError("receipt already exists")
    model_id = os.environ.get("GEXEC_PROBE_MODEL")
    base = os.environ.get("GEXEC_PROBE_BASE_URL")
    key = os.environ.get("GEXEC_PROBE_API_KEY")
    if base and (not model_id or not key):
        raise RuntimeError("explicit base URL requires model and locally supplied key")
    model = build_live_model(model_id, base, key) if model_id else None
    result = await execute_probe(model, model_id)
    result["pax_master"] = "custom-agent tool called; TestModel master"
    with path.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True)
        out.write("\n")
    return "Receipt written successfully."
