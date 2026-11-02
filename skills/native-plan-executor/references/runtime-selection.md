# Active CLI runtime selection

## Rule: choose the current harness, not an installed executable

This skill is an instruction package, not a portable process with a guaranteed `CLINE` or `CODEX` environment variable. Determine its current host **from trusted live tool/session evidence** before deciding which native delegation API to call. The presence of `codex`, `cline`, `CODEX_HOME`, `.codex/`, or `.cline/` on the machine is *not* evidence that the current turn is running inside that harness. Do not shell out to detect a parent process or spawn the other CLI.

Use these signals in descending priority:

1. Inspect the native tools **currently offered to the active agent** and their schemas.
   - **Cline team:** native `team_spawn_teammate` with `team_task`/`team_run_task`/`team_status` and mailbox/wait equivalents.
   - **Codex:** native Codex subagent collaboration tools (such as `spawn_agent`, `send_message`, `followup_task`, `list_agents`, `wait_agent`) with Codex-specific schema/host identity.
   - **Cline subagent:** Cline `spawn_agent` / configured `subagent_<name>` tools in a Cline-identified session, but no usable team tools. A Cline subagent call returns a focused result, not a persistent Codex-style agent thread.
2. When tool names overlap (notably `spawn_agent`), require a positive trusted host identity from the enclosing session/skill loader or a schema unique to that host. Generic delegation tool presence alone is ambiguous.
3. If still ambiguous, request one explicit host choice and verify that runtime's actual native tools are available. User choice is not a substitute for capability proof.

Prefer **Cline team** over Cline one-off subagents for a supplied team definition that needs durable task boards, messages, dependency tracking or resumption. A simple, independent subtree may use Cline subagents only if the plan/team's logical requirements still fit. If the requested native team tools are not enabled, tell the user how to start Cline CLI in team mode (`/team`) or enable tools using `/settings`; **do not start a child `cline` process from inside the skill**.

## Resolution receipt

Before any model selection or spawning, record in the run's `execution.json`:

```json
{
  "runtime": {
    "host": "codex | cline",
    "mode": "codex-native | cline-team | cline-subagent",
    "evidence": ["trusted host and matching live tool/schema identifiers"],
    "capabilities": {
      "spawn": true,
      "message": true,
      "wait": true,
      "status": true,
      "model_override": "supported | unsupported | unverified"
    },
    "limitations": []
  }
}
```

The above is a shape, not an instruction to assume any capability. Record only observed values. On resume, re-resolve runtime and reconcile existing native identities. Never reuse a Codex thread ID as a Cline teammate/run ID or vice versa. A host or delegation-mode change requires explicit reconciliation and, if live identities cannot be safely transferred, a new run; do not claim continuity of a dead native team.

## Selected protocol

- `codex-native`: follow [native-protocol.md](native-protocol.md) and current Codex subagent tool schema.
- `cline-team` / `cline-subagent`: follow [cline-protocol.md](cline-protocol.md) and current Cline team/subagent tool schema.
- Any unsupported or ambiguous capability needed by a mandatory team definition: report a **blocked** result with the missing tool/role/model control. Do not substitute simulated agents, CLI subprocesses, unapproved models or untracked coordination.

Use one master (the current root agent) in all modes. The plan and team definition remain the source of truth; runtime adaptation changes *how* assignments are delivered, not *who* owns them or their acceptance criteria.
