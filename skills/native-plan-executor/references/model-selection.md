# Confirmed leaf-model policy

## Discovery and cost-benefit review

Before spawning any implementation/review agent, enumerate every model advertised by the active native spawn interface. Record exact IDs, supported overrides/efforts, inventory source, retrieval time and coverage. Inspect role-level restrictions; a role can prevent an otherwise advertised model from being used. Do not hard-code a model list or infer account availability from model names.

If a connected Codex model-list interface is available, use its documented `model/list` operation and exhaust pagination; request hidden entries when the interface supports it. Treat this as supplemental catalog evidence: intersect it with the native interface's actual selectable models and role constraints. Do not launch an external Codex process or extract credentials to obtain a catalog. The public API model list does not prove native eligibility. If discovery is incomplete, state exactly what is exposed and what cannot be checked; offer a recommendation within that set or ask for a supported user choice. Never describe a partial set as all account models.

Review the supplied plan/team before ranking leaf candidates. Consider required tools, context/modality, instruction following, coding/review complexity, available verification, expected latency and likely retries/supervision. Prefer the least expensive model likely to complete this work reliably. Show a short comparison of the recommended model and useful alternatives with evidence, limitations and confidence. No mandatory weighted score or invented performance numbers are needed.

Identify billing basis (subscription usage, credits or API currency). Consult current official model/pricing evidence when costs affect the recommendation; API token prices are not actual subscription consumption. Where quantitative costs or quality comparisons are unavailable, use a clearly qualitative recommendation and disclose missing evidence. Do not claim measured best value without measurements. No paid trial runs or benchmarks are required for discovery; propose any such experiment separately if genuinely needed.

Evidence: [Codex model/list](https://learn.chatgpt.com/docs/app-server#models), [Codex pricing and usage](https://learn.chatgpt.com/docs/pricing). Read current documentation when using a version-specific discovery interface.

## Saved selection and monthly gate

Default config: `<CODEX_HOME>/native-plan-executor/model-policy.json`, or `~/.codex/native-plan-executor/model-policy.json` if CODEX_HOME is unset. This is one user-wide choice across projects. It is separate from `config.toml`, installed agent profiles, runtime state and the skill package. No credentials belong in it.

Use the bundled helper with the complete current advertised inventory (replace example IDs with discovered exact IDs):

```bash
python3 <skill-dir>/scripts/model_policy.py status --available <model-id-1> <model-id-2>
```

`status` does not write, renew approval or select a model. It reports whether confirmation is required. For tests or explicit alternate storage, `--config <path>` is available. `--today YYYY-MM-DD` is for controlled validation; actual invocations use the real system-local date. A new calendar month means a changed local YYYY-MM, not thirty elapsed days. A multi-month gap triggers one review on the next invocation. No scheduler runs while the skill is unused.

Initial use, malformed/future-dated configuration, changed month, unavailable model, or incompatible required capability means the approval gate must run. The helper checks dates and advertised availability; the master checks capability/team compatibility. During the same approved month, reuse the selection without re-ranking or prompting, after checking current availability and hard requirements. An explicit user request to change it triggers review immediately.

On a due review, refresh discovery and comparison. Present the proposed exact ID, basis, tradeoff and any uncertainty, then ask one question offering confirmation or a user-specified model. Wait for an actual answer. Even if the recommendation equals last month's selection, renew only after confirmation. Silence, elapsed time, a generic cost preference or a stale approval is not consent. A user-specified model need not win the cost ranking, but it must be supported and compatible; otherwise explain the conflict and request a valid choice. Do not substitute another model silently.

Only after that answer, save through:

```bash
python3 <skill-dir>/scripts/model_policy.py confirm --model <confirmed-id> --available <current-advertised-ids...> --confirmation "Actual user choice or confirmation reference" --basis "Comparison rationale, inventory coverage and cost evidence limitations"
```

The helper records schema version, model ID, confirmation date/month, basis and confirmation note atomically with private file permissions. This command records the master's observed user answer; it cannot independently prove consent. Do not invoke it merely because the user requested this skill enhancement. Existing malformed configuration must be inspected and preserved before a deliberate repair; never silently reset approval. A record is not permission to bypass higher-priority routing or platform restrictions.

No approved model is pre-seeded during skill installation. In particular, historical gpt-6-luna defaults are candidates, not current confirmations.

## Dispatch and changes during execution

Record the config receipt, current inventory/coverage, capability check, requested model and any exposed effective routing in the run's execution record. Pass the exact confirmed ID to native spawn with fresh context when required by the live schema. Master/non-leaf routing remains as defined in the execution protocol.

The monthly check happens at invocation, including a resumed invocation. Do not interrupt a running team merely because the clock crosses a month boundary mid-run. On resume, reconcile existing agents first; a newly confirmed choice governs new dispatch. Existing agents may be reused only if their recorded model selection matches; finish/reconcile active writes before an explicitly recorded replacement, preserving logical agent roles and task ownership. Do not assume a message changes an existing agent's model.

A runtime rejection despite advertised support invalidates availability for that candidate. Pause affected dispatch, record the rejection and request a confirmed replacement; never auto-fallback. If the selected model lacks a required capability on a new plan, do the same even when monthly approval is fresh. Retry behavior cannot rewrite the saved choice.
