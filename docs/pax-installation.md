# Pax durable candidate: local installation and use

Requires Python 3.12, Git, a local Temporal dev server at localhost:7233, and an explicitly authorized OpenAI-compatible endpoint. This branch has been tested with Pax/Harness 0.74.0 and the earlier bridge spike also passed on 0.75.0. Runtime package pins the 0.74.0 candidate. Existing global Pax, Codex and Cline installations are not changed.

## Install in an isolated environment

```bash
git clone --branch feat/pax-durable-multicli https://github.com/Trochez/graph-execution.git
cd graph-execution
uv venv --python 3.12 ../gexec-runtime-venv
uv pip install --python ../gexec-runtime-venv/bin/python -e '.[pax]'
../gexec-runtime-venv/bin/python -m graph_execution_runtime.cli doctor
```

Use your existing Temporal dev server; for a fresh dev installation run `temporal server start-dev --db-filename /your/private/path/temporal.db` in another terminal. Do not start a duplicate listener. The package only accepts the trusted loopback default server. Temporal history stores source and proposals; use a disposable repository without secrets. Do not expose dev Temporal publicly. Do not share raw receipts containing project data.

## Approve the exact route

Set GEXEC_PROBE_API_KEY privately in the environment of each authorized process, not in a file or command history. In bash/zsh use:

```bash
read -rs 'GEXEC_PROBE_API_KEY?Provider API key: ' # zsh
export GEXEC_PROBE_API_KEY
echo
```

In bash use `read -rs -p "Provider API key: " GEXEC_PROBE_API_KEY` then export. Choose your actual endpoint and model, e.g. read them interactively:

```bash
printf "OpenAI-compatible base URL: "; read -r BASE_URL
printf "Exact model ID: "; read -r MODEL_ID
../gexec-runtime-venv/bin/python -m graph_execution_runtime.cli models --base-url "$BASE_URL"
../gexec-runtime-venv/bin/python -m graph_execution_runtime.cli approve-model \
  --base-url "$BASE_URL" --model "openai:$MODEL_ID" --confirmation "openai:$MODEL_ID"
```

The settings may optionally include master_model and master_model_confirmation (both the same exact provider-qualified master ID), on the same endpoint. A planning config's model is the actual master route. Only approve a model you actually choose and that is advertised by the endpoint. If renewing, explicitly archive the old model-policy file before approving a replacement. No automatic fallback. Alias upstream identity may be unknown.

## Complete sequential gexec workflow

Create a private JSON planning config outside the target worktree with keys: plan (absolute Markdown file), workspace (absolute target repository), skill_root (absolute checkout of this repository), run_dir (new absolute directory for stage artifacts outside target worktree), base_url, model (provider-qualified), read_paths (explicit relative context files). Set GEXEC_PIPELINE_CONFIG to that path and GEXEC_RUN_BUNDLE to a new future bundle path outside the target. Launch the actual custom agent:

```bash
../gexec-runtime-venv/bin/pax --agent graph_execution_runtime.pax_bridge:agent --request-limit 60
```

In Pax request: "Use gexec on the configured plan. Complete the first two skills and pause at the operator approval gate." Review the resulting planner and team artifacts. The stage manifest uses the legacy gate and original artifact names. The master must still verify semantic requirements, staffing and review independence.

Prepare a settings JSON file following [the example](../examples/pax/settings.example.json), adapting the actual task IDs, role/parent mappings, scopes and test commands. Set exact existing-parent relative paths; do not put credentials into files, messages or settings. The checks are trusted project commands explicitly chosen by the operator and may execute repository code. Review them first. If the plan needs an unsupported capability (shell-based worker implementation, binary changes, unsupported provider/role overrides, OS sandbox, unresolved gate), do not approve that task.

From the checkout (replace all paths with actual paths), use:

```bash
../gexec-runtime-venv/bin/python -m graph_execution_runtime.cli prepare \
 --plan "$PLAN" --tasks "$RUN_DIR/critical-path-planner/tasks.json" \
 --team "$RUN_DIR/backlog-team-designer/team-definition.json" \
 --settings "$SETTINGS" --workspace "$WORKSPACE" --skill-root "$PWD" \
 --journal "$JOURNAL" --output "$GEXEC_RUN_BUNDLE" --pipeline "$RUN_DIR"
```

For standalone executor with existing structured artifacts, use the same prepare command with --standalone instead of --pipeline. In a separate terminal, with the same approved key and bundle:

```bash
../gexec-runtime-venv/bin/python -m graph_execution_runtime.cli worker --bundle "$GEXEC_RUN_BUNDLE"
```

Resume the existing Pax session and ask it to continue through native-plan-executor, inspect each proposal, verify each integration, and finalize. If using standalone mode launch Pax with GEXEC_RUN_BUNDLE set and GEXEC_PIPELINE_CONFIG unset. Do not pass -m to override the explicitly approved route.

## Operator control and recovery

All commands use the same bundle. The CLI supports start, status, review --task ID --action apply|repair|block --evidence TEXT, verify --task ID, cancel --reason TEXT and finalize. Review actual proposals in Pax before applying. The worker persists workflow state in your Temporal server. Restarting the worker between completed turns is supported by test evidence; in-flight activity interruption may become blocked/uncertain and must not be automatically replayed. A journal intent without done receipt requires manual file/hash reconciliation. No automatic rollback of applied changes.

Record files: journal/records/execution.json, events.jsonl, final-checks.json. The source plan and legacy artifacts are fingerprinted and preserved. Stop the dedicated worker after its own run is finished. The legacy skills need no new package for Codex or Cline.

## Rollback and scope

Do not merge the feature branch as a release until real-host qualification. To stop testing, cancel the run, inspect final status, stop its worker and remove the isolated virtualenv only after preserving evidence. Keep Temporal data and journals until reconciliation is complete. Do not delete user changes or reset the target worktree. Native paths and approval files remain untouched.

This candidate does not support arbitrary project tools, unrestricted shell, delete/rename/binary edits, remote Temporal, arbitrary per-role/provider routes, or OS-enforced worker isolation. It uses bounded whole-turn checkpoints and explicit proposals rather than automatic re-execution of uncertain effects. See the [compatibility ADR](adr/compatibility-spike.md).

## Disposable real Pax executor smoke

After installing the package and starting your existing local Temporal dev server, run `scripts/live_pax_runtime_smoke.py` with the isolated Python, your actual base URL, the exact provider-qualified model ID, the same ID in --confirm-model, and a fresh --output directory outside any project. This makes bounded real model requests and launches Pax once as the root agent, not as a child worker. It uses a new synthetic workspace, a dedicated Temporal queue and private fixture-only approval/database. The original repository and global Pax settings are not changed. Inspect receipt.json; raw pax-local.log remains private. A pass is evidence for this executor fixture only, not the full real-host release matrix.


If the real master exits with a nonzero code, the smoke receipt remains FAIL even when some tasks are done. The runner reports safe log classifications (diagnostic signals, not proven causes) and attempts bounded cancellation/drain. Diagnose a previous fixture without any provider calls: `python -m graph_execution_runtime.diagnostics --root .. --workflow-id YOUR_WORKFLOW_ID`. Do not paste raw `pax-local.log` or credentials. The master uses compact state responses and a combined explicitly approved review/verification tool to reduce repeated model calls; the request limit is not silently increased.


Startup regression guard: the live runner parses runtime modules and checks Temporal health before provider inventory; it preserves the Pax exit and log classifications even if a workflow was never created. Use `python -m graph_execution_runtime.diagnostics --root .. --latest` for the newest fixture, including older fixtures missing a receipt. The `--check-only` live-runner flag performs source and Temporal health checks without provider calls (pass the normal CLI arguments; the output directory is not created). A `NOT_FOUND` from describe after a Pax exit means the workflow was not found, not proof of an unavailable Temporal server.

## Autonomous v2 candidate

See [Pax autonomous operator guide](pax-autonomous.md) for the one-time project profile and single-command run, local Docker tests and live qualification scenarios. The earlier manual bundle instructions apply to restricted v1 only.
