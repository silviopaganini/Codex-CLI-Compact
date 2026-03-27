# Codex Token Benchmark

This folder contains the saved setup for comparing:
- `dg .` / graph-enabled Codex
- plain Codex baseline

## Saved Files

- `restaurant_crm_prompts.txt`
  - fixed 20-prompt suite for `restaurant-crm`
- `codex_token_bench.py`
  - real token benchmark harness for Codex

## Project Used

Source project: a full-stack restaurant CRM app (not included in this repo).

Benchmark copies:

- `/tmp/restaurant-crm-with-graph`
- `/tmp/restaurant-crm-baseline`

If those `/tmp` copies are missing, recreate them with:

```bash
rsync -a --delete --exclude '.git' --exclude 'node_modules' --exclude '.next' --exclude '.dual-graph' \
  '/path/to/your/restaurant-crm/' \
  '/tmp/restaurant-crm-with-graph/'

rsync -a --delete --exclude '.git' --exclude 'node_modules' --exclude '.next' --exclude '.dual-graph' \
  '/path/to/your/restaurant-crm/' \
  '/tmp/restaurant-crm-baseline/'
```

## Run

From this repo:

```bash
python3 bench/codex_token_bench.py /tmp/restaurant-crm-with-graph /tmp/restaurant-crm-baseline
```

To save output:

```bash
python3 bench/codex_token_bench.py /tmp/restaurant-crm-with-graph /tmp/restaurant-crm-baseline | tee /tmp/restaurant_crm_codex_bench.jsonl
```

## What The Harness Does

- builds the graph in the `with-graph` copy
- starts the local MCP server
- registers Codex MCP `dual-graph`
- runs each prompt once with graph
- removes MCP
- runs the same prompt once without graph
- captures real token usage from `codex exec --json`

## Confirmed Smoke Result

One real prompt was verified end-to-end before the full run:

- with graph: `138365`
- without graph: `300563`
- saved: `162198`
- reduction: about `54.0%`

This is only a 1-prompt confirmed result, not the 20-prompt aggregate.

## Important Notes

- The full 20-prompt run uses real Codex tokens and can take a while.
- The harness does not edit files; prompts instruct Codex to answer briefly and not modify code.
- If Codex MCP registration fails, rerun after ensuring no stale `dual-graph` MCP entry is left.
