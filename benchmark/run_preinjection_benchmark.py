#!/usr/bin/env python3
"""3-way benchmark: Normal Claude vs MCP-DGC vs Pre-Injection DGC.

Runs 15 standard prompts through all three modes using `claude -p` with
JSON output.  Appends per-prompt results to a JSONL file (resume support).
Generates a detailed markdown report comparing all three approaches.

Usage:
    python run_preinjection_benchmark.py
    python run_preinjection_benchmark.py --prompts 1,3,5
    python run_preinjection_benchmark.py --modes normal,preinjection
    python run_preinjection_benchmark.py --budget 4000
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from math import ceil
from pathlib import Path
from statistics import mean, median

VERSION = "3.8.32"

ROOT = Path(__file__).resolve().parent
_LOCAL_BIN = ROOT.parent / "bin"
PYTHON = Path(os.environ.get("DG_VENV_PYTHON", os.path.expanduser("~/.dual-graph/venv/bin/python3")))
GRAPH_BUILDER = _LOCAL_BIN / "graph_builder.py"
MCP_SERVER = _LOCAL_BIN / "mcp_graph_server.py"

NORMAL_DIR = ROOT / "normal-claude" / "restaurant-crm"
DGC_DIR = ROOT / "dgc-claude" / "restaurant-crm"
PROMPTS_FILE = ROOT / "prompts.json"
RESULTS_DIR = ROOT / "results"
RAW_FILE = RESULTS_DIR / f"raw_v{VERSION}.jsonl"
REPORT_FILE = RESULTS_DIR / f"benchmark_v{VERSION}.md"

COOLDOWN = 5   # seconds between runs
TIMEOUT = 300  # seconds per prompt

# Make bin/ importable
sys.path.insert(0, str(_LOCAL_BIN))
from context_packer import pack_for_query, estimate_tokens


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[bench] {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------

def find_free_port(start: int = 8200, end: int = 8300) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in range")


def wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"MCP server on port {port} did not become ready")


def stop_process(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def build_graph(project_dir: Path) -> None:
    """Build the info graph for the project."""
    data_dir = project_dir / ".dual-graph"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"Building graph for {project_dir}...")
    result = subprocess.run(
        [str(PYTHON), str(GRAPH_BUILDER), "--root", str(project_dir),
         "--out", str(data_dir / "info_graph.json")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Graph build failed: {result.stderr[-500:]}")
    log("Graph built successfully")


def start_graph_server(project_dir: Path) -> tuple[subprocess.Popen, int]:
    """Start the MCP graph server and return (process, port)."""
    data_dir = project_dir / ".dual-graph"
    port = find_free_port()
    env = os.environ.copy()
    env["DG_DATA_DIR"] = str(data_dir)
    env["DUAL_GRAPH_PROJECT_ROOT"] = str(project_dir)
    env["DG_BASE_URL"] = f"http://127.0.0.1:{port}"
    env["PORT"] = str(port)

    proc = subprocess.Popen(
        [str(PYTHON), str(MCP_SERVER)],
        cwd=str(project_dir),
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_for_port(port)
    log(f"Graph server ready on port {port}")
    return proc, port


def write_mcp_config(port: int) -> Path:
    """Write a temp MCP config with the actual port."""
    config = {
        "mcpServers": {
            "dual-graph": {
                "type": "sse",
                "url": f"http://127.0.0.1:{port}/mcp"
            }
        }
    }
    config_path = RESULTS_DIR / "dgc_mcp_config_live.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


# ---------------------------------------------------------------------------
# Claude runner
# ---------------------------------------------------------------------------

def _clean_env() -> dict:
    """Return a copy of os.environ without nested-session vars."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env.pop("CLAUDE_CODE_SESSION", None)
    return env


def _parse_claude_json(stdout: str) -> dict:
    """Parse JSON from claude --output-format json stdout."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        pass
    for line in stdout.splitlines():
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"No valid JSON in output: {stdout[-500:]}")


def run_claude(
    prompt: str,
    project_dir: Path,
    mcp_config: Path | None = None,
) -> dict:
    """Run `claude -p` and return metrics dict.

    Returns dict with: input_tokens, output_tokens, num_turns, wall_time_s,
    total_cost_usd, cache_creation_tokens, cache_read_tokens, response_text.
    """
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--model", "claude-sonnet-4-6",
        "--no-session-persistence",
        "--dangerously-skip-permissions",
    ]
    if mcp_config:
        cmd.extend(["--mcp-config", str(mcp_config)])

    env = _clean_env()
    wall_start = time.time()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        wall_time = time.time() - wall_start
        return {
            "wall_time_s": round(wall_time, 2),
            "duration_ms": 0,
            "duration_api_ms": 0,
            "input_tokens": 0,
            "input_tokens_raw": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "response_text": "",
            "num_turns": 0,
            "stop_reason": "timeout",
            "error": f"Timeout after {TIMEOUT}s",
        }
    except Exception as e:
        wall_time = time.time() - wall_start
        return {
            "wall_time_s": round(wall_time, 2),
            "duration_ms": 0,
            "duration_api_ms": 0,
            "input_tokens": 0,
            "input_tokens_raw": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "response_text": "",
            "num_turns": 0,
            "stop_reason": "error",
            "error": str(e),
        }

    wall_time = time.time() - wall_start

    if result.returncode != 0:
        return {
            "wall_time_s": round(wall_time, 2),
            "duration_ms": 0,
            "duration_api_ms": 0,
            "input_tokens": 0,
            "input_tokens_raw": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "response_text": "",
            "num_turns": 0,
            "stop_reason": "error",
            "error": f"Claude exited {result.returncode}: {result.stderr[-300:]}",
        }

    data = _parse_claude_json(result.stdout)
    usage = data.get("usage", {})
    raw_input = usage.get("input_tokens", 0)
    cache_create = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    total_input = raw_input + cache_create + cache_read

    return {
        "wall_time_s": round(wall_time, 2),
        "duration_ms": data.get("duration_ms", 0),
        "duration_api_ms": data.get("duration_api_ms", 0),
        "input_tokens": total_input,
        "input_tokens_raw": raw_input,
        "output_tokens": output_tokens,
        "cache_creation_tokens": cache_create,
        "cache_read_tokens": cache_read,
        "total_cost_usd": data.get("total_cost_usd", 0.0),
        "response_text": data.get("result", ""),
        "num_turns": data.get("num_turns", 1),
        "stop_reason": data.get("stop_reason", ""),
    }


# ---------------------------------------------------------------------------
# Pre-injection runner
# ---------------------------------------------------------------------------

def run_preinjection(
    prompt: str,
    project_dir: Path,
    token_budget: int = 5000,
) -> dict:
    """Pack context via context_packer, then run claude -p with NO MCP.

    Returns the same dict as run_claude plus pack_time_s and pack_tokens_est.
    """
    # 1. Time the context pack separately
    pack_start = time.time()
    try:
        # Change to project dir so dg.load_graph() finds .dual-graph/
        orig_cwd = os.getcwd()
        os.chdir(str(project_dir))
        context = pack_for_query(prompt, project_dir, token_budget)
        os.chdir(orig_cwd)
    except Exception as e:
        log(f"  Context pack failed: {e}")
        return {
            "wall_time_s": 0.0,
            "duration_ms": 0,
            "duration_api_ms": 0,
            "input_tokens": 0,
            "input_tokens_raw": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "total_cost_usd": 0.0,
            "response_text": "",
            "num_turns": 0,
            "stop_reason": "error",
            "error": f"Context pack failed: {e}",
            "pack_time_s": round(time.time() - pack_start, 3),
            "pack_tokens_est": 0,
        }

    pack_time = time.time() - pack_start
    pack_tokens = estimate_tokens(context)

    # 2. Build full prompt with context prepended
    full_prompt = (
        f"{context}\n\n---\n\n"
        f"User question: {prompt}\n"
        f"Answer concisely. Do not edit any files."
    )

    # 3. Run claude -p with NO MCP
    result = run_claude(full_prompt, project_dir, mcp_config=None)

    # 4. Add pre-injection-specific fields
    result["pack_time_s"] = round(pack_time, 3)
    result["pack_tokens_est"] = pack_tokens

    return result


# ---------------------------------------------------------------------------
# Quality scoring
# ---------------------------------------------------------------------------

def score_quality(response: str, category: str, prompt: str) -> dict:
    """Score a response 0-50 based on content quality heuristics.

    Scoring dimensions:
        - word_count      (0-8): longer, more detailed answers score higher
        - file_mentions   (0-10): references to actual file paths
        - code_blocks     (0-8): presence of code examples
        - specificity     (0-10): mentions of concrete identifiers
        - structure_score (0-6): headings, lists, organized output
        - category_bonus  (0-8): category-specific quality signals
    """
    if not response or "error" in str(response).lower()[:50]:
        return {
            "total": 0,
            "word_count": 0,
            "file_mentions": 0,
            "code_blocks": 0,
            "specificity": 0,
            "structure_score": 0,
            "category_bonus": 0,
        }

    words = response.split()
    word_count = len(words)

    # Word count score (0-8): reward substantive answers
    if word_count >= 500:
        wc_score = 8
    elif word_count >= 300:
        wc_score = 6
    elif word_count >= 150:
        wc_score = 4
    elif word_count >= 50:
        wc_score = 2
    else:
        wc_score = 0

    # File mentions (0-10): count file path references
    file_patterns = re.findall(
        r'`[a-zA-Z0-9_/\-]+\.[a-zA-Z]{1,5}`'
        r'|[a-zA-Z0-9_/\-]+\.(?:py|ts|tsx|js|jsx|json|yaml|yml|sql|html|css)',
        response,
    )
    file_count = len(set(file_patterns))
    if file_count >= 8:
        file_score = 10
    elif file_count >= 5:
        file_score = 8
    elif file_count >= 3:
        file_score = 6
    elif file_count >= 1:
        file_score = 3
    else:
        file_score = 0

    # Code blocks (0-8)
    code_blocks = response.count("```")
    cb_count = code_blocks // 2  # pairs
    if cb_count >= 3:
        cb_score = 8
    elif cb_count >= 2:
        cb_score = 6
    elif cb_count >= 1:
        cb_score = 4
    else:
        cb_score = 0

    # Specificity (0-10): concrete identifiers like function names, class names
    identifiers = re.findall(
        r'`[a-zA-Z_][a-zA-Z0-9_]*(?:\([^)]*\))?`',
        response,
    )
    ident_count = len(set(identifiers))
    if ident_count >= 15:
        spec_score = 10
    elif ident_count >= 10:
        spec_score = 8
    elif ident_count >= 5:
        spec_score = 5
    elif ident_count >= 2:
        spec_score = 3
    else:
        spec_score = 0

    # Structure (0-6): headings, bullet points, numbered lists
    headings = len(re.findall(r'^#{1,4}\s', response, re.MULTILINE))
    bullets = len(re.findall(r'^[\s]*[-*]\s', response, re.MULTILINE))
    numbered = len(re.findall(r'^[\s]*\d+\.\s', response, re.MULTILINE))
    struct_items = headings + min(bullets, 10) + min(numbered, 10)
    if struct_items >= 10:
        struct_score = 6
    elif struct_items >= 5:
        struct_score = 4
    elif struct_items >= 2:
        struct_score = 2
    else:
        struct_score = 0

    # Category bonus (0-8)
    cat_bonus = 0
    response_lower = response.lower()

    if category == "code_explanation":
        # Reward flow descriptions, step-by-step
        if any(w in response_lower for w in ["flow", "step", "first", "then", "finally"]):
            cat_bonus += 3
        if any(w in response_lower for w in ["endpoint", "route", "handler", "model"]):
            cat_bonus += 3
        if file_count >= 3:
            cat_bonus += 2

    elif category == "bug_fix":
        # Reward root cause analysis
        if any(w in response_lower for w in ["cause", "bug", "issue", "fix", "problem"]):
            cat_bonus += 3
        if any(w in response_lower for w in ["solution", "patch", "change", "modify"]):
            cat_bonus += 3
        if cb_count >= 1:
            cat_bonus += 2

    elif category == "feature_add":
        # Reward design completeness
        if any(w in response_lower for w in ["design", "implement", "create", "add"]):
            cat_bonus += 2
        if any(w in response_lower for w in ["database", "model", "schema", "migration"]):
            cat_bonus += 2
        if any(w in response_lower for w in ["frontend", "backend", "api", "endpoint"]):
            cat_bonus += 2
        if file_count >= 4:
            cat_bonus += 2

    elif category == "refactoring":
        # Reward structural analysis
        if any(w in response_lower for w in ["refactor", "extract", "consolidate", "shared"]):
            cat_bonus += 3
        if any(w in response_lower for w in ["duplicate", "redundant", "reuse", "module"]):
            cat_bonus += 3
        if file_count >= 3:
            cat_bonus += 2

    elif category == "architecture":
        # Reward system-level understanding
        if any(w in response_lower for w in ["architecture", "system", "component", "layer"]):
            cat_bonus += 3
        if any(w in response_lower for w in ["relationship", "dependency", "coupling"]):
            cat_bonus += 3
        if file_count >= 5:
            cat_bonus += 2

    elif category == "debugging":
        # Reward diagnostic approach
        if any(w in response_lower for w in ["debug", "trace", "investigate", "log"]):
            cat_bonus += 3
        if any(w in response_lower for w in ["performance", "bottleneck", "latency", "request"]):
            cat_bonus += 3
        if file_count >= 2:
            cat_bonus += 2

    cat_bonus = min(cat_bonus, 8)

    total = wc_score + file_score + cb_score + spec_score + struct_score + cat_bonus
    return {
        "total": min(total, 50),
        "word_count": wc_score,
        "file_mentions": file_score,
        "code_blocks": cb_score,
        "specificity": spec_score,
        "structure_score": struct_score,
        "category_bonus": cat_bonus,
    }


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_completed_ids(path: Path) -> set[int]:
    """Load already-completed prompt IDs for resume support."""
    completed = set()
    if not path.exists():
        return completed
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            completed.add(entry["id"])
        except (json.JSONDecodeError, KeyError):
            continue
    return completed


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _safe_get(d: dict, key: str, default=0):
    """Safely get a value from a dict, returning default if missing or error."""
    if not isinstance(d, dict) or "error" in d:
        return default
    return d.get(key, default)


def _fmt_cost(cost: float) -> str:
    return f"${cost:.4f}"


def _fmt_pct(value: float) -> str:
    if value > 0:
        return f"+{value:.1f}%"
    return f"{value:.1f}%"


def _pct_change(baseline: float, new: float) -> float:
    if baseline == 0:
        return 0.0
    return ((new - baseline) / baseline) * 100


def generate_report(results: list[dict]) -> str:
    """Generate a detailed markdown report comparing all 3 modes."""
    lines: list[str] = []
    lines.append(f"# DGC v{VERSION} Pre-Injection Benchmark")
    lines.append("")
    lines.append(f"**Date:** {time.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Prompts run:** {len(results)}")
    lines.append(f"**Timeout:** {TIMEOUT}s per prompt | **Cooldown:** {COOLDOWN}s between runs")
    lines.append("")

    # Determine which modes have data
    has_normal = any("normal" in r and not _safe_get(r.get("normal", {}), "error") for r in results)
    has_mcp = any("mcp" in r and not _safe_get(r.get("mcp", {}), "error") for r in results)
    has_pre = any("preinjection" in r and not _safe_get(r.get("preinjection", {}), "error") for r in results)

    all_modes = []
    mode_labels = {}
    if has_normal:
        all_modes.append("normal")
        mode_labels["normal"] = "Normal"
    if has_mcp:
        all_modes.append("mcp")
        mode_labels["mcp"] = "MCP-DGC"
    if has_pre:
        all_modes.append("preinjection")
        mode_labels["preinjection"] = "Pre-Inject"

    # ── Results Summary Table ─────────────────────────────────────────────
    lines.append("## Results Summary")
    lines.append("")

    header_cols = ["ID", "Category"]
    for m in all_modes:
        header_cols.append(f"{mode_labels[m]} Cost")
    if has_pre and has_normal:
        header_cols.append("Pre vs Normal")
    if has_pre and has_mcp:
        header_cols.append("Pre vs MCP")
    lines.append("| " + " | ".join(header_cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(header_cols)) + " |")

    for r in results:
        row = [str(r["id"]), r["category"]]
        costs = {}
        for m in all_modes:
            c = _safe_get(r.get(m, {}), "total_cost_usd", 0.0)
            costs[m] = c
            err = _safe_get(r.get(m, {}), "error", "")
            if err:
                row.append("ERROR")
            else:
                row.append(_fmt_cost(c))
        if has_pre and has_normal:
            if costs.get("normal", 0) > 0 and costs.get("preinjection", 0) > 0:
                row.append(_fmt_pct(_pct_change(costs["normal"], costs["preinjection"])))
            else:
                row.append("N/A")
        if has_pre and has_mcp:
            if costs.get("mcp", 0) > 0 and costs.get("preinjection", 0) > 0:
                row.append(_fmt_pct(_pct_change(costs["mcp"], costs["preinjection"])))
            else:
                row.append("N/A")
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # ── Aggregate Statistics ──────────────────────────────────────────────
    lines.append("## Aggregate Statistics")
    lines.append("")

    metrics_keys = [
        ("Total Cost (USD)", "total_cost_usd", _fmt_cost),
        ("Avg Cost (USD)", "total_cost_usd", None),  # handled specially
        ("Total Input Tokens", "input_tokens", lambda x: f"{x:,}"),
        ("Total Output Tokens", "output_tokens", lambda x: f"{x:,}"),
        ("Avg Wall Time (s)", "wall_time_s", None),
        ("Avg Turns", "num_turns", None),
        ("Avg Quality Score", None, None),  # handled specially
    ]

    agg_header = ["Metric"] + [mode_labels[m] for m in all_modes]
    lines.append("| " + " | ".join(agg_header) + " |")
    lines.append("| " + " | ".join(["---"] * len(agg_header)) + " |")

    for label, key, fmt_fn in metrics_keys:
        row = [label]
        for m in all_modes:
            valid = [r for r in results if m in r and not _safe_get(r.get(m, {}), "error")]
            if not valid:
                row.append("N/A")
                continue

            if label == "Total Cost (USD)":
                val = sum(_safe_get(r[m], key, 0.0) for r in valid)
                row.append(_fmt_cost(val))
            elif label == "Avg Cost (USD)":
                vals = [_safe_get(r[m], "total_cost_usd", 0.0) for r in valid]
                row.append(_fmt_cost(mean(vals)) if vals else "N/A")
            elif label.startswith("Total"):
                val = sum(_safe_get(r[m], key, 0) for r in valid)
                row.append(fmt_fn(val))
            elif label == "Avg Wall Time (s)":
                vals = [_safe_get(r[m], "wall_time_s", 0.0) for r in valid]
                row.append(f"{mean(vals):.1f}" if vals else "N/A")
            elif label == "Avg Turns":
                vals = [_safe_get(r[m], "num_turns", 1) for r in valid]
                row.append(f"{mean(vals):.1f}" if vals else "N/A")
            elif label == "Avg Quality Score":
                q_key = f"{m}_quality"
                vals = [r.get(q_key, {}).get("total", 0) for r in results if q_key in r]
                row.append(f"{mean(vals):.1f}/50" if vals else "N/A")
            else:
                row.append("N/A")
        lines.append("| " + " | ".join(row) + " |")

    # Pre-injection specific stats
    if has_pre:
        valid_pre = [r for r in results if "preinjection" in r and not _safe_get(r.get("preinjection", {}), "error")]
        if valid_pre:
            pack_times = [_safe_get(r["preinjection"], "pack_time_s", 0.0) for r in valid_pre]
            pack_tokens = [_safe_get(r["preinjection"], "pack_tokens_est", 0) for r in valid_pre]
            lines.append(f"| Avg Pack Time (s) | " + " | ".join(
                [f"{mean(pack_times):.3f}" if m == "preinjection" else "---" for m in all_modes]
            ) + " |")
            lines.append(f"| Avg Pack Tokens | " + " | ".join(
                [f"{mean(pack_tokens):.0f}" if m == "preinjection" else "---" for m in all_modes]
            ) + " |")

    lines.append("")

    # ── Turn Count Table ──────────────────────────────────────────────────
    lines.append("## Turn Count (Key Metric)")
    lines.append("")
    turn_header = ["ID"] + [f"{mode_labels[m]} Turns" for m in all_modes]
    lines.append("| " + " | ".join(turn_header) + " |")
    lines.append("| " + " | ".join(["---"] * len(turn_header)) + " |")

    for r in results:
        row = [str(r["id"])]
        for m in all_modes:
            turns = _safe_get(r.get(m, {}), "num_turns", 0)
            err = _safe_get(r.get(m, {}), "error", "")
            if err:
                row.append("ERR")
            else:
                row.append(str(turns))
        lines.append("| " + " | ".join(row) + " |")

    # Turn count averages
    lines.append("")
    avg_row = ["**Average**"]
    for m in all_modes:
        valid = [r for r in results if m in r and not _safe_get(r.get(m, {}), "error")]
        if valid:
            avg_turns = mean([_safe_get(r[m], "num_turns", 1) for r in valid])
            avg_row.append(f"**{avg_turns:.1f}**")
        else:
            avg_row.append("N/A")
    lines.append("| " + " | ".join(avg_row) + " |")
    lines.append("")

    # ── Category Breakdown ────────────────────────────────────────────────
    lines.append("## Category Breakdown")
    lines.append("")

    categories = sorted(set(r["category"] for r in results))
    for cat in categories:
        cat_results = [r for r in results if r["category"] == cat]
        lines.append(f"### {cat.replace('_', ' ').title()}")
        lines.append("")

        cat_header = ["Metric"] + [mode_labels[m] for m in all_modes]
        lines.append("| " + " | ".join(cat_header) + " |")
        lines.append("| " + " | ".join(["---"] * len(cat_header)) + " |")

        for metric_label, metric_key in [
            ("Avg Cost", "total_cost_usd"),
            ("Avg Turns", "num_turns"),
            ("Avg Wall Time", "wall_time_s"),
            ("Avg Quality", None),
        ]:
            row = [metric_label]
            for m in all_modes:
                valid = [r for r in cat_results if m in r and not _safe_get(r.get(m, {}), "error")]
                if not valid:
                    row.append("N/A")
                    continue
                if metric_label == "Avg Quality":
                    q_key = f"{m}_quality"
                    vals = [r.get(q_key, {}).get("total", 0) for r in cat_results if q_key in r]
                    row.append(f"{mean(vals):.1f}/50" if vals else "N/A")
                elif metric_key == "total_cost_usd":
                    vals = [_safe_get(r[m], metric_key, 0.0) for r in valid]
                    row.append(_fmt_cost(mean(vals)))
                elif metric_key == "num_turns":
                    vals = [_safe_get(r[m], metric_key, 1) for r in valid]
                    row.append(f"{mean(vals):.1f}")
                elif metric_key == "wall_time_s":
                    vals = [_safe_get(r[m], metric_key, 0.0) for r in valid]
                    row.append(f"{mean(vals):.1f}s")
            lines.append("| " + " | ".join(row) + " |")

        lines.append("")

    # ── Per-Prompt Details ────────────────────────────────────────────────
    lines.append("## Per-Prompt Details")
    lines.append("")

    for r in results:
        lines.append(f"### Prompt {r['id']} — {r['category']}")
        lines.append(f"> {r['prompt'][:120]}{'...' if len(r['prompt']) > 120 else ''}")
        lines.append("")

        detail_header = ["Metric"] + [mode_labels[m] for m in all_modes]
        lines.append("| " + " | ".join(detail_header) + " |")
        lines.append("| " + " | ".join(["---"] * len(detail_header)) + " |")

        for metric_label, metric_key, fmt in [
            ("Cost", "total_cost_usd", _fmt_cost),
            ("Input Tokens", "input_tokens", lambda x: f"{x:,}"),
            ("Output Tokens", "output_tokens", lambda x: f"{x:,}"),
            ("Cache Create", "cache_creation_tokens", lambda x: f"{x:,}"),
            ("Cache Read", "cache_read_tokens", lambda x: f"{x:,}"),
            ("Turns", "num_turns", str),
            ("Wall Time", "wall_time_s", lambda x: f"{x:.1f}s"),
            ("Quality", None, None),
        ]:
            row = [metric_label]
            for m in all_modes:
                d = r.get(m, {})
                if _safe_get(d, "error"):
                    row.append("ERROR")
                    continue
                if metric_label == "Quality":
                    q_key = f"{m}_quality"
                    q = r.get(q_key, {})
                    row.append(f"{q.get('total', 0)}/50")
                else:
                    val = _safe_get(d, metric_key, 0)
                    row.append(fmt(val))
            lines.append("| " + " | ".join(row) + " |")

        # Show pack time for pre-injection
        if has_pre and "preinjection" in r and not _safe_get(r.get("preinjection", {}), "error"):
            pack_row = ["Pack Time"]
            for m in all_modes:
                if m == "preinjection":
                    pack_row.append(f"{_safe_get(r['preinjection'], 'pack_time_s', 0):.3f}s")
                else:
                    pack_row.append("---")
            lines.append("| " + " | ".join(pack_row) + " |")

            pack_tok_row = ["Pack Tokens"]
            for m in all_modes:
                if m == "preinjection":
                    pack_tok_row.append(f"{_safe_get(r['preinjection'], 'pack_tokens_est', 0):,}")
                else:
                    pack_tok_row.append("---")
            lines.append("| " + " | ".join(pack_tok_row) + " |")

        lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append(f"*Generated by run_preinjection_benchmark.py v{VERSION}*")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"3-way benchmark v{VERSION}: Normal vs MCP-DGC vs Pre-Injection DGC",
    )
    parser.add_argument(
        "--prompts",
        default="",
        help="Comma-separated prompt IDs to run (e.g. 1,3,5). Skips resume check.",
    )
    parser.add_argument(
        "--modes",
        default="normal,mcp,preinjection",
        help="Comma-separated modes to benchmark (default: normal,mcp,preinjection)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Token budget for pre-injection context packing (default: 5000)",
    )
    args = parser.parse_args()

    # Parse modes
    active_modes = {m.strip() for m in args.modes.split(",") if m.strip()}
    valid_modes = {"normal", "mcp", "preinjection"}
    invalid = active_modes - valid_modes
    if invalid:
        log(f"ERROR: Invalid modes: {invalid}. Valid: {valid_modes}")
        return 1
    log(f"Active modes: {sorted(active_modes)}")

    # Parse prompt filter
    prompt_filter: set[int] | None = None
    if args.prompts.strip():
        prompt_filter = {int(x.strip()) for x in args.prompts.split(",") if x.strip()}

    # Verify directories exist
    if not NORMAL_DIR.exists():
        log(f"ERROR: Normal dir not found: {NORMAL_DIR}")
        return 1
    if not DGC_DIR.exists():
        log(f"ERROR: DGC dir not found: {DGC_DIR}")
        return 1

    # Load prompts
    if not PROMPTS_FILE.exists():
        log(f"ERROR: Prompts file not found: {PROMPTS_FILE}")
        return 1
    prompts = json.loads(PROMPTS_FILE.read_text(encoding="utf-8"))

    # Apply prompt filter
    if prompt_filter:
        prompts = [p for p in prompts if p["id"] in prompt_filter]
        if not prompts:
            log(f"ERROR: No prompts matched IDs {prompt_filter}")
            return 1
        log(f"Running {len(prompts)} selected prompt(s): {sorted(prompt_filter)}")
        completed: set[int] = set()
    else:
        completed = load_completed_ids(RAW_FILE)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if completed:
        remaining = len([p for p in prompts if p["id"] not in completed])
        log(f"Resuming: {len(completed)} done, {remaining} remaining")

    # Build graph for DGC_DIR (needed by both MCP and pre-injection modes)
    if "mcp" in active_modes or "preinjection" in active_modes:
        build_graph(DGC_DIR)

    # Start MCP server only if MCP mode is active
    server_proc: subprocess.Popen | None = None
    mcp_config: Path | None = None
    if "mcp" in active_modes:
        server_proc, port = start_graph_server(DGC_DIR)
        mcp_config = write_mcp_config(port)

    try:
        all_results: list[dict] = []

        # Load existing results for report generation
        if RAW_FILE.exists():
            for line in RAW_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        all_results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        for p in prompts:
            pid = p["id"]
            if pid in completed:
                log(f"Skipping prompt {pid} (already done)")
                continue

            category = p["category"]
            prompt_text = p["prompt"] + "\nAnswer concisely. Do not edit any files."

            log(f"{'=' * 60}")
            log(f"Prompt {pid}/{len(prompts)} [{category}]")
            log(f"{'=' * 60}")

            entry: dict = {
                "id": pid,
                "category": category,
                "prompt": p["prompt"],
            }

            # ── Pre-injection run ─────────────────────────────────────────
            if "preinjection" in active_modes:
                log(f"  Pre-injection run (budget={args.budget})...")
                pre_result = run_preinjection(
                    p["prompt"], DGC_DIR, token_budget=args.budget,
                )
                entry["preinjection"] = pre_result
                pre_err = _safe_get(pre_result, "error", "")
                if pre_err:
                    log(f"  Pre-injection FAILED: {pre_err}")
                else:
                    log(
                        f"  Pre-inject: {pre_result['input_tokens']} in / "
                        f"{pre_result['output_tokens']} out / "
                        f"${pre_result['total_cost_usd']:.4f} / "
                        f"{pre_result['wall_time_s']}s / "
                        f"pack={pre_result['pack_time_s']:.3f}s"
                    )
                time.sleep(COOLDOWN)

            # ── MCP-DGC run ───────────────────────────────────────────────
            if "mcp" in active_modes:
                log(f"  MCP-DGC run...")
                mcp_result = run_claude(prompt_text, DGC_DIR, mcp_config)
                entry["mcp"] = mcp_result
                mcp_err = _safe_get(mcp_result, "error", "")
                if mcp_err:
                    log(f"  MCP FAILED: {mcp_err}")
                else:
                    log(
                        f"  MCP: {mcp_result['input_tokens']} in / "
                        f"{mcp_result['output_tokens']} out / "
                        f"${mcp_result['total_cost_usd']:.4f} / "
                        f"{mcp_result['wall_time_s']}s"
                    )
                time.sleep(COOLDOWN)

            # ── Normal run ────────────────────────────────────────────────
            if "normal" in active_modes:
                log(f"  Normal run...")
                normal_result = run_claude(prompt_text, NORMAL_DIR)
                entry["normal"] = normal_result
                normal_err = _safe_get(normal_result, "error", "")
                if normal_err:
                    log(f"  Normal FAILED: {normal_err}")
                else:
                    log(
                        f"  Normal: {normal_result['input_tokens']} in / "
                        f"{normal_result['output_tokens']} out / "
                        f"${normal_result['total_cost_usd']:.4f} / "
                        f"{normal_result['wall_time_s']}s"
                    )

            # ── Score quality for all modes ───────────────────────────────
            for mode in active_modes:
                if mode in entry and not _safe_get(entry.get(mode, {}), "error"):
                    response_text = _safe_get(entry[mode], "response_text", "")
                    entry[f"{mode}_quality"] = score_quality(
                        response_text, category, p["prompt"],
                    )
                else:
                    entry[f"{mode}_quality"] = score_quality("", category, p["prompt"])

            # ── Log comparison ────────────────────────────────────────────
            scores = {}
            for mode in active_modes:
                q = entry.get(f"{mode}_quality", {})
                scores[mode] = q.get("total", 0)
            log(f"  Quality scores: {scores}")

            # ── Save to JSONL ─────────────────────────────────────────────
            with open(RAW_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=True) + "\n")
            log(f"  Saved prompt {pid}")

            # Replace any existing entry with same ID for report
            all_results = [r for r in all_results if r["id"] != pid]
            all_results.append(entry)

            time.sleep(COOLDOWN)

        # ── Generate report ───────────────────────────────────────────────
        all_results.sort(key=lambda r: r["id"])
        report = generate_report(all_results)
        REPORT_FILE.write_text(report, encoding="utf-8")
        log(f"Report written to {REPORT_FILE}")

    except KeyboardInterrupt:
        log("Interrupted — partial results saved")
        # Still generate report from what we have
        if all_results:
            all_results.sort(key=lambda r: r["id"])
            report = generate_report(all_results)
            REPORT_FILE.write_text(report, encoding="utf-8")
            log(f"Partial report written to {REPORT_FILE}")
    finally:
        stop_process(server_proc)
        if server_proc is not None:
            log("Graph server stopped")

    log("Benchmark complete!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
