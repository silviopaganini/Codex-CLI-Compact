#!/usr/bin/env python3
"""Local dashboard server for info-graph + token usage tracking."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

# core/ lives one level up from dashboard/
import sys as _sys
_CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(_CORE_DIR) not in _sys.path:
    _sys.path.insert(0, str(_CORE_DIR))

from graph_builder import scan
from dg import retrieve


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
GRAPH_JSON = DATA_DIR / "info_graph.json"
TOKEN_LOG = DATA_DIR / "token_usage.jsonl"
BENCH_LOG_PATH = Path.home() / ".dual-graph" / "bench_log.jsonl"
PROJECT_ROOT = Path(
    os.environ.get(
        "DUAL_GRAPH_PROJECT_ROOT",
        "/app/project",  # default clone target in Railway (set via GITHUB_REPO_URL)
    )
).resolve()
API_TOKEN = os.environ.get("DG_API_TOKEN", "").strip()


class Handler(BaseHTTPRequestHandler):
    def _auth_failed(self) -> bool:
        if not API_TOKEN:
            return False
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {API_TOKEN}":
            return False
        self.send_error(HTTPStatus.UNAUTHORIZED, "Unauthorized")
        return True

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path.startswith("/api/") and self._auth_failed():
                return
            if parsed.path == "/api/info-graph":
                query = parse_qs(parsed.query)
                self.serve_info_graph(full=(query.get("full", ["0"])[0] == "1"))
                return
            if parsed.path == "/api/token-summary":
                self.serve_token_summary()
                return
            if parsed.path == "/api/bench-log":
                self.serve_bench_log()
                return
            if parsed.path == "/healthz":
                self.write_json({"ok": True})
                return
            if parsed.path in {"/", "/index.html"}:
                self.serve_static("index.html")
                return
            self.serve_static(parsed.path.lstrip("/"))
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/webhook":
                self.handle_webhook()
                return
            if parsed.path.startswith("/api/") and self._auth_failed():
                return
            if parsed.path == "/api/scan":
                self.trigger_scan()
                return
            if parsed.path == "/api/token-event":
                self.record_token_event()
                return
            if parsed.path == "/api/tokenize":
                self.tokenize_text()
                return
            if parsed.path == "/api/chat-fix":
                self.chat_fix()
                return
            if parsed.path == "/api/token-reset":
                self.reset_token_log()
                return
            if parsed.path == "/api/bench-log-reset":
                BENCH_LOG_PATH.write_text("", encoding="utf-8")
                self.write_json({"ok": True})
                return
            if parsed.path == "/ingest-graph":
                self.ingest_graph()
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def handle_webhook(self) -> None:
        """POST /webhook — git pull + rescan. Called by GitHub/GitLab push hook."""
        repo_root = PROJECT_ROOT
        pull_out: str = ""
        pull_err: str = ""
        pulled = False

        git_dir = repo_root / ".git"
        if git_dir.exists():
            try:
                proc = subprocess.run(
                    ["git", "-C", str(repo_root), "pull", "--ff-only"],
                    capture_output=True, text=True, timeout=60, check=False,
                )
                pull_out = proc.stdout.strip()
                pull_err = proc.stderr.strip()
                pulled = proc.returncode == 0
            except Exception as e:  # noqa: BLE001
                pull_err = str(e)
        else:
            pull_err = "not a git repo"

        graph = scan(repo_root)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")

        self.write_json({
            "ok": True, "pulled": pulled,
            "pull_stdout": pull_out, "pull_stderr": pull_err,
            "node_count": graph["node_count"], "edge_count": graph["edge_count"],
        })

    def ingest_graph(self) -> None:
        """POST /ingest-graph — accept a pre-built graph JSON from a local machine."""
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "Empty body")
            return
        body = self.rfile.read(length)
        try:
            graph = json.loads(body)
            if "nodes" not in graph or "edges" not in graph:
                raise ValueError("missing nodes/edges")
        except Exception as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid graph JSON: {exc}")
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        self.write_json({
            "ok": True,
            "node_count": graph.get("node_count", len(graph["nodes"])),
            "edge_count": graph.get("edge_count", len(graph["edges"])),
        })

    def trigger_scan(self) -> None:
        graph = scan(PROJECT_ROOT)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        GRAPH_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        self.write_json({"ok": True, "node_count": graph["node_count"], "edge_count": graph["edge_count"]})

    def serve_info_graph(self, full: bool = False) -> None:
        if not GRAPH_JSON.exists():
            graph = scan(PROJECT_ROOT)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            GRAPH_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        payload = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
        if not full:
            payload["nodes"] = payload.get("nodes", [])[:250]
            payload["edges"] = payload.get("edges", [])[:500]
            payload["truncated"] = True
            payload["nodes_total"] = payload.get("node_count", 0)
            payload["edges_total"] = payload.get("edge_count", 0)
        self.write_json(payload)

    def record_token_event(self) -> None:
        body = self.read_json_body()
        if body is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": body.get("mode", "unknown"),
            "prompt_chars": int(body.get("prompt_chars", 0)),
            "prompt_tokens": int(body.get("prompt_tokens", 0)),
            "completion_tokens": int(body.get("completion_tokens", 0)),
            "total_tokens": int(body.get("total_tokens", 0)),
            "notes": str(body.get("notes", "")),
        }
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with TOKEN_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
        self.write_json({"ok": True})

    def serve_token_summary(self) -> None:
        events: list[dict] = []
        if TOKEN_LOG.exists():
            for line in TOKEN_LOG.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        total = sum(int(ev.get("total_tokens", 0)) for ev in events)
        by_mode: dict[str, int] = {}
        for ev in events:
            mode = str(ev.get("mode", "unknown"))
            by_mode[mode] = by_mode.get(mode, 0) + int(ev.get("total_tokens", 0))

        self.write_json({
            "event_count": len(events),
            "total_tokens": total,
            "by_mode": by_mode,
            "recent": events[-30:],
        })

    def serve_bench_log(self) -> None:
        entries: list[dict] = []
        if BENCH_LOG_PATH.exists():
            for line in BENCH_LOG_PATH.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        total_with = 0
        total_without = 0
        by_project: dict[str, dict] = {}

        for e in entries:
            project = str(e.get("project", "unknown"))
            mode = str(e.get("mode", ""))
            if project not in by_project:
                by_project[project] = {"with": 0, "without": 0}

            if mode == "live":
                tw = int(e.get("tokens_with", 0) or 0)
                two = int(e.get("tokens_without", 0) or 0)
                total_with += tw
                total_without += two
                by_project[project]["with"] += tw
                by_project[project]["without"] += two
            elif mode == "session":
                label = str(e.get("label", ""))
                tokens = int(e.get("tokens", 0) or 0)
                if "without" in label:
                    total_without += tokens
                    by_project[project]["without"] += tokens
                elif "with" in label:
                    total_with += tokens
                    by_project[project]["with"] += tokens

        total_saved = total_without - total_with
        pct_saved = round((total_saved / total_without * 100), 1) if total_without > 0 else 0.0

        recent: list[dict] = []
        for e in entries[-50:]:
            mode = str(e.get("mode", ""))
            proj = str(e.get("project", "")).split("/")[-1]
            if mode == "live":
                tw = int(e.get("tokens_with", 0) or 0)
                two = int(e.get("tokens_without", 0) or 0)
                recent.append({
                    "ts": str(e.get("ts", "")), "project": proj, "mode": "live",
                    "with": tw, "without": two, "saved": two - tw,
                    "prompt": str(e.get("prompt", ""))[:220],
                    "dur_with": int(e.get("dur_with", 0) or 0),
                    "dur_without": int(e.get("dur_without", 0) or 0),
                })
            elif mode == "session":
                ps = list(e.get("prompts") or [])
                label = str(e.get("label", ""))
                tokens = int(e.get("tokens", 0) or 0)
                is_without = "without" in label
                recent.append({
                    "ts": str(e.get("ts", "")), "project": proj,
                    "mode": f"session/{label}", "label": label, "tokens": tokens,
                    "tok_with": 0 if is_without else tokens,
                    "tok_without": tokens if is_without else 0,
                    "inp": int(e.get("inp", 0) or 0), "out": int(e.get("out", 0) or 0),
                    "prompt": str(ps[0])[:220] if ps else "",
                    "prompt_count": len(ps),
                })

        self.write_json({
            "total_with": total_with, "total_without": total_without,
            "total_saved": total_saved, "pct_saved": pct_saved,
            "entry_count": len(entries),
            "by_project": [
                {"project": p, "with": v["with"], "without": v["without"], "saved": v["without"] - v["with"]}
                for p, v in by_project.items()
            ],
            "recent": list(reversed(recent)),
        })

    def tokenize_text(self) -> None:
        body = self.read_json_body()
        if body is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        text = str(body.get("text", ""))
        provider = str(body.get("provider", "heuristic"))
        model = str(body.get("model", "claude-sonnet-4-6"))

        if provider == "anthropic":
            count, mode, err = self.count_tokens_anthropic(text, model)
            if err:
                self.write_json({"ok": False, "provider": provider, "mode": "fallback",
                                 "tokens": max(1, len(text) // 4), "error": err})
                return
            self.write_json({"ok": True, "provider": provider, "mode": mode, "tokens": count})
            return

        # Default heuristic
        self.write_json({"ok": True, "provider": "heuristic", "mode": "heuristic", "tokens": max(1, len(text) // 4)})

    def count_tokens_anthropic(self, text: str, model: str) -> tuple[int, str, str | None]:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return 0, "fallback", "ANTHROPIC_API_KEY is not set"

        payload = {"model": model, "messages": [{"role": "user", "content": text}]}
        raw = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url="https://api.anthropic.com/v1/messages/count_tokens",
            data=raw, method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return 0, "fallback", f"Anthropic HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')}"
        except Exception as e:  # noqa: BLE001
            return 0, "fallback", f"Anthropic request failed: {e}"

        for key in ("input_tokens", "tokens", "token_count"):
            if key in data:
                try:
                    return int(data[key]), "anthropic_count_tokens", None
                except (TypeError, ValueError):
                    pass
        return 0, "fallback", f"Unexpected response: {data}"

    def reset_token_log(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TOKEN_LOG.write_text("", encoding="utf-8")
        self.write_json({"ok": True})

    def chat_fix(self) -> None:
        body = self.read_json_body()
        if body is None:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid JSON")
            return

        query = str(body.get("query", "")).strip()
        if not query:
            self.send_error(HTTPStatus.BAD_REQUEST, "query is required")
            return

        top_files = int(body.get("top_files", 8) or 8)
        top_edges = int(body.get("top_edges", 20) or 20)
        max_grep_hits = int(body.get("max_grep_hits", 40) or 40)

        if not GRAPH_JSON.exists():
            graph = scan(PROJECT_ROOT)
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            GRAPH_JSON.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        graph = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))

        rel = retrieve(graph, query, top_files, top_edges)
        grep_hits = self.run_grep_for_query(query, max_hits=max_grep_hits)

        summary_lines = ["Use these files first (higher score = higher priority):"]
        for f in rel.files[:min(6, len(rel.files))]:
            score = f.get("_score", 0)
            role = f.get("_role", "n/a")
            summary_lines.append(f"- {f.get('id')}  (score: {score}, role: {role})")
        if grep_hits:
            summary_lines.append("")
            summary_lines.append("Highest-signal grep hits:")
            for h in grep_hits[:8]:
                summary_lines.append(f"- {h['file']}:{h['line']}  {h['text']}")

        self.write_json({
            "ok": True, "query": query,
            "project_root": str(PROJECT_ROOT),
            "summary": "\n".join(summary_lines),
            "graph_files": rel.files, "graph_edges": rel.edges,
            "grep_hits": grep_hits,
        })

    def extract_terms(self, query: str) -> list[str]:
        words = re.findall(r"[A-Za-z0-9_]+", query.lower())
        stop = {
            "a", "an", "the", "and", "for", "with", "from", "that", "this", "what", "when", "then",
            "need", "want", "fix", "update", "make", "can", "will", "how", "into", "have", "you",
            "your", "please", "show", "different", "differently", "to", "in",
        }
        seen: set[str] = set()
        out = []
        for w in words:
            if len(w) >= 3 and w not in stop and w not in seen:
                seen.add(w)
                out.append(w)
        return out

    def run_grep_for_query(self, query: str, max_hits: int = 40) -> list[dict]:
        terms = self.extract_terms(query)[:4]
        if not terms:
            return []
        hits: list[dict] = []
        for term in terms:
            try:
                proc = subprocess.run(
                    ["rg", "-n", "-S", "--max-count", "20", term, "."],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=20, check=False,
                )
            except Exception:
                continue
            if proc.returncode not in (0, 1):
                continue
            for line in proc.stdout.splitlines():
                if len(hits) >= max_hits:
                    break
                parts = line.split(":", 2)
                if len(parts) < 3:
                    continue
                hits.append({"term": term, "file": parts[0], "line": parts[1], "text": parts[2][:220]})
            if len(hits) >= max_hits:
                break
        return hits

    def serve_static(self, path: str) -> None:
        safe = (STATIC_DIR / path).resolve()
        if STATIC_DIR.resolve() not in safe.parents and safe != STATIC_DIR.resolve():
            self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
            return
        if not safe.exists() or not safe.is_file():
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        ctype = "text/plain; charset=utf-8"
        if safe.suffix == ".html":
            ctype = "text/html; charset=utf-8"
        elif safe.suffix == ".css":
            ctype = "text/css; charset=utf-8"
        elif safe.suffix == ".js":
            ctype = "application/javascript; charset=utf-8"
        elif safe.suffix == ".json":
            ctype = "application/json; charset=utf-8"

        data = safe.read_bytes()
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def read_json_body(self) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        payload = self.rfile.read(length) if length > 0 else b"{}"
        try:
            return json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def write_json(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def log_message(self, fmt: str, *args: object) -> None:
        return


def main() -> None:
    host = os.environ.get("DUAL_GRAPH_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("DUAL_GRAPH_PORT", "8787")))
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Dashboard server: http://{host}:{port}")
    print(f"Project root scan target: {PROJECT_ROOT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
