#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = Path(os.environ.get("DG_CORE_DIR", str(ROOT.parent)))
PYTHON = Path(os.environ.get("DG_VENV_PYTHON", os.path.expanduser("~/.dual-graph/venv/bin/python3")))
GRAPH_BUILDER = CORE / "graph_builder.py"
MCP_SERVER = CORE / "mcp_graph_server.py"
PROMPTS_FILE = ROOT / "bench" / "restaurant_crm_prompts.txt"


def log(msg: str) -> None:
    print(f"[bench] {msg}", file=sys.stderr, flush=True)


def load_prompts() -> list[str]:
    return [line.strip() for line in PROMPTS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def find_free_port(start: int = 8080, end: int = 8100) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("no free port in 8080-8099")


def wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.5)
    raise RuntimeError(f"MCP server on port {port} did not become ready")


def run(cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, text=True, capture_output=True)


def codex_tokens(project_dir: Path, prompt: str) -> tuple[int, str]:
    log(f"codex exec start: {project_dir}")
    cmd = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        "-C",
        str(project_dir),
        prompt,
    ]
    res = run(cmd)
    log(f"codex exec done: {project_dir} rc={res.returncode}")
    if res.returncode != 0:
        stderr_tail = res.stderr[-1000:]
        stdout_tail = res.stdout[-2000:]
        raise RuntimeError(f"codex exec failed: stderr={stderr_tail}\nstdout={stdout_tail}")
    total = 0
    last_text = ""
    for line in res.stdout.splitlines():
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "item.completed":
            item = obj.get("item", {})
            if item.get("type") == "agent_message":
                last_text = str(item.get("text", "")).strip()
        if obj.get("type") == "turn.completed":
            usage = obj.get("usage", {})
            total = int(usage.get("input_tokens", 0)) + int(usage.get("cached_input_tokens", 0)) + int(usage.get("output_tokens", 0))
    if total <= 0:
        raise RuntimeError(f"no token usage found in codex output: {res.stdout[-1000:]}")
    return total, last_text


def ensure_dual_graph_policy(project_dir: Path) -> None:
    policy = """# Dual-Graph Context Policy

Use the local dual-graph MCP server for efficient code navigation.

Rules:
- Always call graph_continue first before broad exploration.
- Prefer graph_read on recommended files over broad search.
- Keep answers concise and do not modify files.
"""
    (project_dir / "CODEX.md").write_text(policy, encoding="utf-8")
    gitignore = project_dir / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = set(existing.splitlines())
    for item in (".dual-graph/", ".dual-graph-context/"):
        lines.add(item)
    gitignore.write_text("\n".join(sorted(x for x in lines if x.strip())) + "\n", encoding="utf-8")


def start_graph_server(project_dir: Path) -> tuple[subprocess.Popen[str], int]:
    data_dir = project_dir / ".dual-graph"
    data_dir.mkdir(parents=True, exist_ok=True)
    log(f"graph build start: {project_dir}")
    scan = run([str(PYTHON), str(GRAPH_BUILDER), "--root", str(project_dir), "--out", str(data_dir / "info_graph.json")])
    if scan.returncode != 0:
        raise RuntimeError(f"graph build failed: {scan.stderr[-1000:]}")
    log(f"graph build done: {project_dir}")
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
    log(f"graph server ready on port {port}")
    return proc, port


def stop_process(proc: subprocess.Popen[str] | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def codex_mcp_remove() -> None:
    log("codex mcp remove start")
    run(["codex", "mcp", "remove", "dual-graph"])
    log("codex mcp remove done")


def codex_mcp_add(port: int) -> None:
    log(f"codex mcp add start: {port}")
    res = run(["codex", "mcp", "add", "--transport", "http", "dual-graph", f"http://127.0.0.1:{port}/mcp"])
    if res.returncode != 0:
        alt = run(["codex", "mcp", "add", "dual-graph", "--url", f"http://127.0.0.1:{port}/mcp"])
        if alt.returncode != 0:
            raise RuntimeError(f"codex mcp add failed: {res.stderr[-500:]} {alt.stderr[-500:]}")
    log(f"codex mcp add done: {port}")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: codex_token_bench.py <with-graph-dir> <baseline-dir>")
        return 2
    with_dir = Path(sys.argv[1]).resolve()
    base_dir = Path(sys.argv[2]).resolve()
    prompts = load_prompts()
    ensure_dual_graph_policy(with_dir)

    proc = None
    results: list[dict[str, object]] = []
    exit_code = 0
    failure: dict[str, object] | None = None
    try:
        proc, port = start_graph_server(with_dir)
        for idx, prompt in enumerate(prompts, start=1):
            log(f"prompt {idx}/{len(prompts)} start")
            full_prompt = f"{prompt}\nAnswer briefly. Do not edit files."
            codex_mcp_remove()
            codex_mcp_add(port)
            graph_tokens, graph_answer = codex_tokens(with_dir, full_prompt)
            codex_mcp_remove()
            base_tokens, base_answer = codex_tokens(base_dir, full_prompt)
            results.append(
                {
                    "index": idx,
                    "prompt": prompt,
                    "tokens_with_graph": graph_tokens,
                    "tokens_without_graph": base_tokens,
                    "saved_tokens": base_tokens - graph_tokens,
                    "saved_percent": round(((base_tokens - graph_tokens) / base_tokens * 100.0), 1) if base_tokens else 0.0,
                    "graph_answer_preview": graph_answer[:160],
                    "baseline_answer_preview": base_answer[:160],
                }
            )
            print(json.dumps(results[-1], ensure_ascii=True))
            log(f"prompt {idx}/{len(prompts)} done")
        total_with = sum(int(r["tokens_with_graph"]) for r in results)
        total_without = sum(int(r["tokens_without_graph"]) for r in results)
        summary = {
            "prompt_count": len(results),
            "total_with_graph": total_with,
            "total_without_graph": total_without,
            "saved_tokens": total_without - total_with,
            "saved_percent": round(((total_without - total_with) / total_without * 100.0), 1) if total_without else 0.0,
        }
        print("SUMMARY " + json.dumps(summary, ensure_ascii=True))
    except Exception as exc:
        exit_code = 1
        failure = {
            "type": "benchmark_error",
            "completed_prompts": len(results),
            "error": str(exc),
        }
        print(json.dumps(failure, ensure_ascii=True))
        summary = {
            "prompt_count": len(results),
            "total_with_graph": sum(int(r["tokens_with_graph"]) for r in results),
            "total_without_graph": sum(int(r["tokens_without_graph"]) for r in results),
            "saved_tokens": sum(int(r["saved_tokens"]) for r in results),
            "saved_percent": round(
                (
                    sum(int(r["saved_tokens"]) for r in results)
                    / sum(int(r["tokens_without_graph"]) for r in results)
                    * 100.0
                ),
                1,
            ) if results else 0.0,
            "partial": True,
        }
        print("SUMMARY " + json.dumps(summary, ensure_ascii=True))
    finally:
        codex_mcp_remove()
        stop_process(proc)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
