# Restaurant CRM Codex Token Benchmark Report (Partial)

Date: March 11, 2026

Status: Partial. The full 20-prompt rerun could not be completed on March 11, 2026 because `codex exec` hit a usage-limit error on the first graph-enabled prompt. Raw failure output is saved in `bench/restaurant_crm_benchmark_raw.jsonl`.

## Confirmed Prior Result

One real prompt had already been confirmed before this rerun:

- Prompt 1
- With graph: `138365`
- Without graph: `300563`
- Saved: `162198`
- Reduction: `54.0%`

This confirmed result appears in the saved benchmark notes and user-provided context, but it is only one prompt and not a completed 20-prompt aggregate.

## Current Totals

Confirmed totals currently available:

- Prompt count with confirmed token data: `1`
- Total tokens with graph: `138365`
- Total tokens without graph: `300563`
- Total saved tokens: `162198`
- Saved percent: `54.0%`

March 11, 2026 rerun totals:

- Prompt count completed in this rerun: `0 / 20`
- Total tokens with graph: `0`
- Total tokens without graph: `0`
- Total saved tokens: `0`
- Saved percent: `0.0%`
- Run status: `partial`

## Per-Prompt Results

| # | Prompt summary | Status | With graph | Without graph | Saved | Reduction | Notes |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Restaurant onboarding entry points | Confirmed prior result | 138365 | 300563 | 162198 | 54.0% | Prior real run confirmed; March 11 rerun of this same prompt was blocked before completion by Codex usage limit. |
| 2 | Customer authentication flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 3 | WhatsApp webhook flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 4 | Restaurant location setup/update flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 5 | Order creation path | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 6 | Dashboard analytics/stats loading | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 7 | Wallet/payout implementation | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 8 | Customer favorites handling | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 9 | Admin/support ticket handling | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 10 | Payment/refund path | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 11 | Menu management flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 12 | Websocket order/notification updates | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 13 | File/image uploads | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 14 | Restaurant settings flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 15 | Notification state/dropdown behavior | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 16 | Customer address management | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 17 | Scheduled/background task endpoints | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 18 | Revenue chart/analytics visualization | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 19 | Restaurant registration/login flow | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |
| 20 | Central API client layers | Not run | - | - | - | - | Blocked by usage limit before suite could proceed. |

## Quality Comparison

Only one prompt has confirmed answer data, so this section is necessarily limited.

- Graph-enabled answer quality: Based on the previously confirmed first prompt, the graph-assisted answer stayed relevant to the exact file-location request.
- Baseline answer quality: Based on that same confirmed prompt, the baseline run was broader and noisier while consuming far more tokens.
- Evidence limit: No March 11, 2026 prompt completed, so there is no 20-prompt quality comparison yet.

## Failures, Retries, and Suspicious Items

- Sandbox limitation: the local MCP server could not bind to `0.0.0.0:8080` inside the sandbox, so the benchmark had to be rerun with escalation.
- CLI compatibility note: `codex mcp add --transport http ...` is not accepted by installed `codex-cli 0.105.0`; the harness fallback `codex mcp add dual-graph --url ...` worked.
- Hard blocker: on March 11, 2026, direct reproduction of prompt 1 failed with a Codex usage-limit error indicating retry availability on March 18, 2026 at 1:54 PM.
- Additional environment warnings: Codex also emitted state database migration warnings for `~/.codex/state_5.sqlite`, but the explicit usage-limit error was the decisive blocker.
- Suspicious prompts: none identified from prompt content. The failure was environmental, not prompt-specific.

## Final Verdict

The single confirmed result is strong and promising: a `54.0%` token reduction on a real prompt is meaningful. It is not strong enough to claim a public 20-prompt benchmark result yet, because the March 11, 2026 rerun completed `0` new prompts and the full suite remains unverified.

Publicly defensible claim today:

- A real first prompt was previously confirmed at `54.0%` token savings.
- The full 20-prompt benchmark is still pending rerun after Codex quota resets.

Public claim to avoid today:

- Any statement implying a completed 20-prompt aggregate or project-wide average.
