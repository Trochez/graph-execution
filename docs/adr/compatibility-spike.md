# Multi-CLI compatibility spike — preflight status

**Decision:** infrastructure feasibility PASS; NO_GO for production release until live agent qualification is available.
**Baseline:** `9ff68208acbbb822f30784f130e23c9db446dcfa` (main).
**Scope:** B01–B05 of the multi-CLI implementation plan; no production skill behavior changed.

## Observed evidence

- The repository main commit matched the audited baseline. The feature branch was created from that SHA.
- [Legacy baseline CI](https://github.com/Trochez/graph-execution/actions/runs/45882538401) passed on Linux/Python 3.14.4: critical-path-planner 4, backlog-team-designer 10, native-plan-executor 11, gexec 10; 35 total. [Repeated baseline](https://github.com/Trochez/graph-execution/actions/runs/45882703365) also passed. These tests do not certify live agent tools.
- The local implementation environment lacked Pax, Codex, Cline, Temporal, pydantic-graph, and Pydantic AI. TCP to localhost:7233 was refused; direct GitHub and PyPI DNS resolution failed. The GitHub connector and CI were usable as alternatives.
- The [first credential-free spike](https://github.com/Trochez/graph-execution/actions/runs/45882703523) failed before dependencies were installed: python3.12 was unavailable. The workflow now explicitly provisions Python 3.12 with a pinned setup-python action. [Corrected run](https://github.com/Trochez/graph-execution/actions/runs/45882755170) completed successfully: dependency installation, CLI help/import checks, and the Graph/Temporal integration probe all passed.
- The corrected spike verified a real local Temporal test service with Pydantic Graph inside an activity; parent/child workflow, duplicate update, signal while workers are stopped, worker restart and replay. Output: ready=[b], receipts=[m1], reply=peer-contract-v1, activity_executions=1; no live model calls. This is infrastructure feasibility only, not agent or production protocol qualification.
- Tested candidate versions: Python 3.12.16, pydantic-ai-pax 0.74.0, pydantic-ai-harness 0.74.0, pydantic-ai-slim 2.74.0, pydantic-graph 2.74.0, temporalio 1.36.0. These are not yet a release lock. Installed Pax help confirms --prompt, --agent, --model, --session-id, --resume, --database and --request-limit; --agent bypasses plugins.
- User-reported macOS collector receipt (2026-11-26T19:21:11Z, commit 9ac83f804cd66b53973cc02e218a896d2cea30f6): clean checkout, baseline ancestor verified, all four helper suites exited 0, pax/codex/cline/temporal/uv/git present and local Temporal TCP open. System Python 3.9.6 had no Pydantic/Temporal packages; the actual Pax environment is separate or not yet inspected. Live host qualification NOT_RUN.
- Official [Pax documentation](https://pydantic.dev/docs/ai/pax/) describes custom agents using `--agent` without Pax plugins; the [Temporal integration guide](https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/) describes the durability capability. The choice of bridge and actual compatibility remains unverified.

## Resume requirements

Run the non-mutating collector on a clean checkout of this branch, in the intended Python environment. For example:

```bash
git clone --branch feat/pax-durable-multicli https://github.com/Trochez/graph-execution.git graph-execution-preflight
cd graph-execution-preflight
python3 scripts/preflight_multicli.py --output ../graph-execution-preflight.json
```

Keep credentials and raw sensitive logs local. The collector only verifies baseline metadata, executable/package presence, local TCP reachability and helper test exits. Its zero exit status is not G0/G1 approval. In an authorized environment with the actual Pax installation, approved provider/model, and Temporal dev service, capture B02/B03 live evidence: skill discovery, authenticated bridge, independent real Harness agents, peer tool access, exact model routing, checkpoints/permission enforcement, worker recovery and replay. Record exact versions and test receipts. Verify live Codex and Cline capabilities for legacy qualification; do not infer them from installed binaries.

## Gate decision

- B01/B04: repository identity, clean macOS clone and existing helper tests established; live host qualification not completed.
- B02: partial: live Pax provider connectivity and independent live Harness peer tools passed; scoped implementation permissions and full host qualification remain pending.
- B03: Graph/Temporal and live Harness peer probe PASS; recovery during agent execution and production authorization not yet demonstrated.
- B05: blocked. No ADR freeze, release lock, runtime adapter, or support claims.
- B06–B24: not started because required feasibility prerequisites remain unresolved. No changes to the four production skills or their current runtime selection/model policies; no merge.

This branch is for inspection and continuation, not release. Do not approve the PR as an implementation of Pax support until the original gates pass.

## macOS continuation (2026-11-26)

Operator-reported Python 3.12.15 isolated installation and local Graph/Temporal spike PASS (same versions as Linux CI; replay/restart and duplicate update proven). Existing uv-managed Pax 0.75.0 supports `--agent`, `--model`, `--prompt`, and returned GEXEC_PAX_OK through its configured model. Its workspace was explicitly reported untrusted. A plain text answer is not tool capability proof. No credential, private path or effective model identity was retained.

Added a narrowly scoped Harness Skills and Temporal peer probe, plus a custom Pax agent bridge probe; their CI tests use TestModel only. The live peer mode requires an explicitly approved provider/model; no provider secret is stored or printed. These are feasibility experiments, not a production adapter. They use separate Agent instances with the Harness Skills capability, no Coder shell/write tools, and a whole-turn Temporal activity boundary. Coder permission/checkpoint interoperability, authenticated production bridge, direct durable per-tool execution, stock Pax profile integration and native Codex/Cline smoke remain unverified. A TestModel result is not live host qualification. The gate stays NO_GO pending required live evidence.

## Peer feasibility evidence (2026-11-26)

- At commit 5b244226da27ff26799fcf418d75f93b6fe42c61, [CI run 45884035851](https://github.com/Trochez/graph-execution/actions/runs/45884035851) passed both 0.74.0 and 0.75.0 matrices, including actual Pax --agent invocation using TestModel and a receipt from the tool callback. Skill catalog: all four skills. No live provider credentials in CI.
- Operator-reported macOS receipt at the same commit: offline and live probes PASS, two independent agent turns, four model requests, two activity attempts, peer_ack=true, consumer_verified=true, replay=true, all four skills found. A provider-qualified model was explicitly requested through the local OpenAI-compatible router; upstream effective route was not independently verified. No endpoint, exact model alias, credentials or user path recorded here.
- Selected candidate seam: documented custom-agent entrypoint with explicitly composed Harness capabilities; Temporal activities for bounded turns, with workflow-authoritative mailboxes. Do not expose default unrestricted Coder Shell or recursive SubAgents in the scoped worker. See [Harness FileSystem](https://pydantic.dev/docs/ai/harness/filesystem/) and [permissions](https://pydantic.dev/docs/ai/harness/permissions/). This is a candidate, not a completed G1 freeze. Production command execution requires separate isolation/authorization; file tool restrictions are not an OS sandbox.
- New focused checks: synthetic positive/negative filesystem scope, read-only reviewer tool inventory, worker replacement at the publisher checkpoint, consumer output derived from the received tool value rather than a copied nonce. New checks await their own CI result. No automatic repeat of in-flight external effects. Existing live receipt remains associated only with its original revision.
