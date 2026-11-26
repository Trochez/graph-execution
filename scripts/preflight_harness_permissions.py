"""Credential-free scoped Harness filesystem feasibility check.

Only synthetic temporary files. No Shell, SubAgents or provider requests.
TestModel/FunctionModel cannot establish adversarial OS-level sandbox security.
"""
from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from pydantic_ai import Agent, ModelResponse, TextPart, ToolCallPart, models
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import FileSystem

models.ALLOW_MODEL_REQUESTS = False


async def run_call(root: Path, tool: str, args: dict, read_only: bool = False):
    offered = set()
    observed = []

    def model(messages, info):
        offered.update(t.name for t in info.function_tools)
        for msg in messages:
            for part in msg.parts:
                if part.part_kind in ("tool-return", "retry-prompt"):
                    observed.append(part)
        if not observed:
            if tool not in offered:
                return ModelResponse(parts=[TextPart("unavailable")])
            return ModelResponse(parts=[ToolCallPart(tool, args)])
        return ModelResponse(parts=[TextPart("finished")])

    agent = Agent(FunctionModel(model), capabilities=[
        LocalWorkspace(str(root)),
        FileSystem(tools=["read_file", "write_file"], allowed_patterns=["owned.txt", "protected.txt"],
                   read_only_patterns=["protected.txt"], content_hashes=False, read_only=read_only),
    ])
    await agent.run("Synthetic scope test.", usage_limits=UsageLimits(request_limit=3, tool_calls_limit=2))
    assert offered <= {"read_file", "write_file"}, offered
    return offered, observed


async def main():
    with tempfile.TemporaryDirectory(prefix="gexec-permission-") as tmp:
        root = Path(tmp) / "work"
        root.mkdir()
        outside = Path(tmp) / "outside.txt"
        outside.write_text("outside-sentinel")
        protected = root / "protected.txt"
        protected.write_text("protected-sentinel")
        owned = root / "owned.txt"
        owned.write_text("before")
        await run_call(root, "write_file", {"path": "owned.txt", "content": "after"})
        assert owned.read_text() == "after", "positive write did not execute"
        for target in ("protected.txt", "unowned.txt", "../outside.txt"):
            _, observed = await run_call(root, "write_file", {"path": target, "content": "forbidden"})
            assert observed, f"no tool attempt for {target}"
        assert protected.read_text() == "protected-sentinel"
        assert outside.read_text() == "outside-sentinel"
        assert not (root / "unowned.txt").exists()
        offered, _ = await run_call(root, "write_file", {"path": "owned.txt", "content": "forbidden"}, read_only=True)
        assert "write_file" not in offered and owned.read_text() == "after"
    print(json.dumps({"probe": "PASS", "owned_write": True, "protected_write_denied": True,
                      "out_of_scope_write_denied": True, "path_escape_denied": True,
                      "reviewer_write_tool_absent": True, "shell_tools_absent": True,
                      "live_model_calls": 0, "os_sandbox_qualification": False}))


if __name__ == "__main__":
    asyncio.run(main())
