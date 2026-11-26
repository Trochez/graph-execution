# Multi-CLI compatibility spike — preflight status

**Decision:** NO_GO for production Pax implementation until G0/G1 live evidence is available.
**Baseline:** `9ff68208acbbb822f30784f130e23c9db446dcfa` (main).
**Scope:** B01–B05 of the multi-CLI implementation plan; no production skill behavior changed.

## Observed evidence

- The repository main commit matched the audited baseline. The feature branch was created from that SHA.
- [Legacy baseline CI](https://github.com/Trochez/graph-execution/actions/runs/45882538401) passed on Linux/Python 3.14.4: critical-path-planner 4, backlog-team-designer 10, native-plan-executor 11, gexec 10; 35 total. [Repeated baseline](https://github.com/Trochez/graph-execution/actions/runs/45882703365) also passed. These tests do not certify live agent tools.
- The local implementation environment lacked Pax, Codex, Cline, Temporal, pydantic-graph, and Pydantic AI. TCP to localhost:7233 was refused; direct GitHub and PyPI DNS resolution failed. The GitHub connector and CI were usable as alternatives.
- The [first credential-free spike](https://github.com/Trochez/graph-execution/actions/runs/45882703523) failed before dependencies were installed: python3.12 was unavailable. The workflow now explicitly provisions Python 3.12 with a pinned setup-python action. [Corrected run](https://github.com/Trochez/graph-execution/actions/runs/45882755170) was queued when this receipt was authored; inspect its actual conclusion.
- The spike attempts a real local Temporal test service with Pydantic Graph inside an activity; parent/child workflow, duplicate update, signal while workers are stopped, worker restart and replay. It also attempts installed CLI help and import probes. A pass is infrastructure feasibility only, not agent or production protocol qualification. Candidate dependency versions are not a release lock.
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

- B01/B04: repository identity and existing helper tests established; local clone and live host qualification not completed.
- B02: blocked (no real Pax session/provider).
- B03: credential-free probe added; full live Harness/Temporal interoperability not demonstrated.
- B05: blocked. No ADR freeze, release lock, runtime adapter, or support claims.
- B06–B24: not started because required feasibility prerequisites remain unresolved. No changes to the four production skills or their current runtime selection/model policies; no merge.

This branch is for inspection and continuation, not release. Do not approve the PR as an implementation of Pax support until the original gates pass.
