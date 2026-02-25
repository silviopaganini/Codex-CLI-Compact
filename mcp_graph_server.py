#!/usr/bin/env python3
"""MCP gateway exposing dual-graph retrieval/read/impact tools."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import urllib.request

# Suppress all INFO-level logs so the Claude CLI terminal stays clean
logging.basicConfig(level=logging.ERROR)
for _logger in ("uvicorn", "uvicorn.error", "uvicorn.access", "mcp", "anyio"):
    logging.getLogger(_logger).setLevel(logging.ERROR)
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except Exception:  # noqa: BLE001
    FastMCP = None  # type: ignore[assignment]

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from graph_builder import scan as _gb_scan
except Exception:  # noqa: BLE001
    _gb_scan = None  # type: ignore[assignment]

try:
    from dg import retrieve as _dg_retrieve
except Exception:  # noqa: BLE001
    _dg_retrieve = None  # type: ignore[assignment]


DG_BASE = os.environ.get("DG_BASE_URL", "http://127.0.0.1:8787")
DG_API_TOKEN = os.environ.get("DG_API_TOKEN", "").strip()
PROJECT_ROOT = Path(
    os.environ.get(
        "DUAL_GRAPH_PROJECT_ROOT",
        "/app/project",  # default clone target in Railway (set via GITHUB_REPO_URL)
    )
).resolve()
# DG_DATA_DIR: where graph JSON + action graph + cache are stored.
# Defaults to <script_dir>/data (Railway mode).
# Set to PROJECT_ROOT/.dual-graph for local mode so data persists with the project.
DG_DATA_DIR = Path(
    os.environ.get("DG_DATA_DIR", str(Path(__file__).resolve().parent / "data"))
)
LOG_FILE = DG_DATA_DIR / "mcp_tool_calls.jsonl"
ACTION_GRAPH_FILE = DG_DATA_DIR / "chat_action_graph.json"
RETRIEVAL_CACHE_FILE = DG_DATA_DIR / "retrieval_cache.json"
SYMBOL_INDEX_FILE = DG_DATA_DIR / "symbol_index.json"
HARD_MAX_READ_CHARS = int(os.environ.get("DG_HARD_MAX_READ_CHARS", "4000"))
TURN_READ_BUDGET_CHARS = int(os.environ.get("DG_TURN_READ_BUDGET_CHARS", "18000"))
ENFORCE_REUSE_GATE = str(os.environ.get("DG_ENFORCE_REUSE_GATE", "1")).strip() not in {"0", "false", "False"}
ENFORCE_SINGLE_RETRIEVE = str(os.environ.get("DG_ENFORCE_SINGLE_RETRIEVE", "1")).strip() not in {"0", "false", "False"}
ENFORCE_READ_ALLOWLIST = str(os.environ.get("DG_ENFORCE_READ_ALLOWLIST", "1")).strip() not in {"0", "false", "False"}
FALLBACK_MAX_CALLS_PER_TURN = int(os.environ.get("DG_FALLBACK_MAX_CALLS_PER_TURN", "1"))
RETRIEVE_CACHE_TTL_SEC = int(os.environ.get("DG_RETRIEVE_CACHE_TTL_SEC", "900"))

# Process-local state for adaptive budgeting and dedupe.
TURN_STATE: dict[str, Any] = {
    "query_key": "",
    "used_chars": 0,
    "seen_reads": {},  # key: (file, query, anchor) -> content
    "reuse_gate_candidates": [],
    "reuse_gate_satisfied": False,
    "retrieved_files": [],
    "retrieve_count": 0,
    "last_retrieve_out": None,
    "fallback_calls": 0,
}


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8")
    headers = {"content-type": "application/json"}
    if DG_API_TOKEN:
        headers["authorization"] = f"Bearer {DG_API_TOKEN}"
    req = urllib.request.Request(
        url=f"{DG_BASE}{path}",
        data=raw,
        method="POST",
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(path: str) -> dict[str, Any]:
    req = urllib.request.Request(url=f"{DG_BASE}{path}", method="GET")
    if DG_API_TOKEN:
        req.add_header("authorization", f"Bearer {DG_API_TOKEN}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Module-level cache for info graph and symbol index, keyed by file mtime.
# Avoids re-parsing MB-sized JSON on every tool call.
_INFO_GRAPH_CACHE: dict[str, Any] | None = None
_INFO_GRAPH_MTIME: int = -1
_SYMBOL_INDEX_CACHE: dict[str, Any] | None = None
_SYMBOL_INDEX_MTIME: int = -1


def _local_info_graph() -> dict[str, Any] | None:
    """Read the info-graph from local DG_DATA_DIR without HTTP. Returns None if unavailable.
    Results are cached in memory and invalidated when the file mtime changes."""
    global _INFO_GRAPH_CACHE, _INFO_GRAPH_MTIME  # noqa: PLW0603
    graph_json = DG_DATA_DIR / "info_graph.json"
    if not graph_json.exists():
        return None
    try:
        current_mtime = int(graph_json.stat().st_mtime_ns)
        if _INFO_GRAPH_CACHE is not None and current_mtime == _INFO_GRAPH_MTIME:
            return _INFO_GRAPH_CACHE
        data = json.loads(graph_json.read_text(encoding="utf-8"))
        # Strip content from file nodes — retrieval doesn't use it, saves RAM.
        # Railway-mode graph_read reads info_graph.json directly (separate path).
        for node in data.get("nodes", []):
            node.pop("content", None)
        _INFO_GRAPH_CACHE = data
        _INFO_GRAPH_MTIME = current_mtime
        return data
    except Exception:
        return None


def _build_symbol_index(graph: dict[str, Any]) -> dict[str, Any]:
    """Build a flat {symbol_id: metadata} dict for O(1) graph_read lookup."""
    index: dict[str, Any] = {}
    for node in graph.get("nodes", []):
        if node.get("kind") == "symbol":
            node_id = str(node.get("id", ""))
            if node_id:
                index[node_id] = {
                    "line_start": node.get("line_start", 0),
                    "line_end": node.get("line_end", 0),
                    "body_hash": node.get("body_hash", ""),
                    "confidence": node.get("confidence", ""),
                    "path": node.get("path", ""),
                }
    return index


def _load_symbol_index() -> dict[str, Any]:
    """Load symbol index with in-memory caching keyed by file mtime."""
    global _SYMBOL_INDEX_CACHE, _SYMBOL_INDEX_MTIME  # noqa: PLW0603
    if not SYMBOL_INDEX_FILE.exists():
        return {}
    try:
        current_mtime = int(SYMBOL_INDEX_FILE.stat().st_mtime_ns)
        if _SYMBOL_INDEX_CACHE is not None and current_mtime == _SYMBOL_INDEX_MTIME:
            return _SYMBOL_INDEX_CACHE
        data = json.loads(SYMBOL_INDEX_FILE.read_text(encoding="utf-8"))
        _SYMBOL_INDEX_CACHE = data
        _SYMBOL_INDEX_MTIME = current_mtime
        return data
    except Exception:
        return {}


def _local_chat_fix(query: str, top_files: int, top_edges: int) -> dict[str, Any] | None:
    """Run retrieval locally from the graph file, bypassing /api/chat-fix HTTP call.
    Returns None if local retrieval is unavailable (falls back to HTTP)."""
    if _dg_retrieve is None:
        return None
    g = _local_info_graph()
    if g is None:
        return None
    try:
        rel = _dg_retrieve(g, query, top_files, top_edges)
        return {
            "ok": True,
            "query": query,
            "graph_files": rel.files,
            "graph_edges": rel.edges,
            "grep_hits": [],
        }
    except Exception:
        return None


def _is_local_file_ref(value: str) -> bool:
    if not value:
        return False
    if value.startswith("@"):
        return False
    # Strip symbol suffix (e.g. "src/auth.ts::handleLogin" → "src/auth.ts")
    file_part = value.split("::")[0] if "::" in value else value
    if ":" in file_part:  # URL-like (http:, C:\)
        return False
    if "/" not in file_part:
        return False
    return "." in file_part.split("/")[-1]


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _query_terms(query: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_]+", query.lower())
    stop = {
        "a", "an", "the", "and", "or", "to", "for", "with", "in", "on", "by", "of",
        "please", "can", "could", "would", "should", "will", "use", "update", "fix",
        "make", "show", "this", "that", "it",
    }
    out: list[str] = []
    seen = set()
    for w in words:
        if len(w) < 3 or w in stop or w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out[:8]


def _query_key(query: str) -> str:
    return " ".join(_query_terms(query))


def _excerpt_by_terms(text: str, terms: list[str], max_chars: int) -> str:
    if not terms:
        return text[:max_chars]
    lines = text.splitlines()
    if not lines:
        return text[:max_chars]
    picks: list[str] = []
    seen_blocks: set[int] = set()
    for idx, line in enumerate(lines):
        blob = line.lower()
        if not any(t in blob for t in terms):
            continue
        start = max(0, idx - 12)
        end = min(len(lines), idx + 13)
        if start in seen_blocks:
            continue
        seen_blocks.add(start)
        block = "\n".join(lines[start:end])
        picks.append(block)
        if sum(len(x) for x in picks) >= max_chars:
            break
    if not picks:
        return text[:max_chars]
    out = "\n\n/* --- excerpt --- */\n\n".join(picks)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out


def _log_tool(name: str, payload: dict[str, Any]) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool": name,
        "payload": payload,
    }
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_action_graph() -> dict[str, Any]:
    if not ACTION_GRAPH_FILE.exists():
        return {"nodes": [], "edges": [], "files": {}, "actions": []}
    try:
        return json.loads(ACTION_GRAPH_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"nodes": [], "edges": [], "files": {}, "actions": []}


def _save_action_graph(g: dict[str, Any]) -> None:
    ACTION_GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTION_GRAPH_FILE.write_text(json.dumps(g, indent=2), encoding="utf-8")


def _ensure_node(g: dict[str, Any], node_id: str, node_type: str, meta: dict[str, Any] | None = None) -> None:
    nodes = g.setdefault("nodes", [])
    if any(n.get("id") == node_id for n in nodes):
        return
    row = {"id": node_id, "type": node_type}
    if meta:
        row["meta"] = meta
    nodes.append(row)


def _add_edge(g: dict[str, Any], frm: str, to: str, rel: str, meta: dict[str, Any] | None = None) -> None:
    edges = g.setdefault("edges", [])
    # Use epoch seconds (not ISO string) to save space.
    row: dict[str, Any] = {"from": frm, "to": to, "rel": rel, "ts": int(datetime.now(timezone.utc).timestamp())}
    if meta:
        row["meta"] = meta
    edges.append(row)
    # Keep last 500 edges only.
    if len(edges) > 500:
        del edges[:-500]


def _slim_payload(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Strip large fields from action payloads before storing."""
    keep: dict[str, Any] = {"kind": kind}
    for k in ("file", "query", "mode", "pattern", "response_chars", "overlap"):
        if k in payload:
            keep[k] = payload[k]
    return keep


def _record_action(kind: str, payload: dict[str, Any]) -> None:
    g = _load_action_graph()
    actions = g.setdefault("actions", [])
    # Store only slim metadata — never full file content.
    actions.append({"ts": int(datetime.now(timezone.utc).timestamp()), "kind": kind, "payload": _slim_payload(kind, payload)})
    if len(actions) > 300:
        del actions[:-300]
    _save_action_graph(g)


def _load_retrieval_cache() -> dict[str, Any]:
    if not RETRIEVAL_CACHE_FILE.exists():
        return {"entries": {}}
    try:
        data = json.loads(RETRIEVAL_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"entries": {}}
        if "entries" not in data or not isinstance(data["entries"], dict):
            data["entries"] = {}
        # Eagerly evict expired entries on load so file never grows stale.
        now = int(datetime.now(timezone.utc).timestamp())
        data["entries"] = {
            k: v for k, v in data["entries"].items()
            if isinstance(v, dict) and now - int(v.get("created_epoch", 0)) <= RETRIEVE_CACHE_TTL_SEC
        }
        return data
    except Exception:
        return {"entries": {}}


def _save_retrieval_cache(cache: dict[str, Any]) -> None:
    RETRIEVAL_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RETRIEVAL_CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def _cache_key(query: str, top_files: int, top_edges: int) -> str:
    qk = _query_key(query)
    return f"{qk}|tf={top_files}|te={top_edges}"


def _file_mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return -1


def _retrieval_entry_valid(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    created = int(entry.get("created_epoch", 0) or 0)
    if created <= 0:
        return False
    now = int(datetime.now(timezone.utc).timestamp())
    if now - created > RETRIEVE_CACHE_TTL_SEC:
        return False
    files = entry.get("files", [])
    mtimes = entry.get("mtimes_ns", {})
    if not isinstance(files, list) or not isinstance(mtimes, dict):
        return False
    for rel in files:
        if not isinstance(rel, str) or not rel:
            return False
        # Symbol IDs (file::symbol) → check mtime of the base file on disk.
        file_path = rel.split("::")[0] if "::" in rel else rel
        p = (PROJECT_ROOT / file_path).resolve()
        current = _file_mtime_ns(p)
        if current < 0:
            return False
        if int(mtimes.get(rel, -2)) != current:
            return False
    return True


def _invalidate_retrieval_cache_for_files(changed_files: list[str]) -> int:
    cache = _load_retrieval_cache()
    entries = cache.get("entries", {})
    if not isinstance(entries, dict):
        return 0
    changed = set(changed_files)
    # Also match symbol IDs whose base file is in the changed set.
    changed_bases = {f.split("::")[0] if "::" in f else f for f in changed_files}
    kill_keys = []
    for key, ent in entries.items():
        files = ent.get("files", [])
        if not isinstance(files, list):
            continue
        if any(f in changed or (f.split("::")[0] if "::" in f else f) in changed_bases for f in files):
            kill_keys.append(key)
    for k in kill_keys:
        entries.pop(k, None)
    cache["entries"] = entries
    _save_retrieval_cache(cache)
    return len(kill_keys)


def _search_action_history(query: str, limit: int = 10) -> dict[str, Any]:
    g = _load_action_graph()
    qterms = set(_query_terms(query))
    actions = g.get("actions", [])
    files_meta = g.get("files", {})

    # Recent relevant actions — return only slim metadata, never full payload.
    action_hits: list[dict[str, Any]] = []
    for a in reversed(actions):
        payload = a.get("payload", {})
        # Score against slim payload only (already stripped of large content).
        blob = " ".join(str(v) for v in payload.values()).lower()
        overlap = sum(1 for t in qterms if t in blob)
        if overlap <= 0 and qterms:
            continue
        action_hits.append({"kind": a.get("kind"), "file": payload.get("file", ""), "overlap": overlap})
        if len(action_hits) >= limit:
            break

    # Relevant cached files — slim response, no cached_content.
    file_hits: list[dict[str, Any]] = []
    for file, meta in files_meta.items():
        cached_terms = set(meta.get("query_terms", []))
        overlap = len(qterms & cached_terms) if qterms else 0
        if qterms and overlap <= 0:
            continue
        file_hits.append({
            "file": file,
            "overlap": overlap,
            "edited_count": int(meta.get("edited_count", 0)),
        })
    file_hits.sort(key=lambda x: (-x["overlap"], -x["edited_count"], x["file"]))
    return {"action_hits": action_hits, "file_hits": file_hits[:limit]}


def build_server(host: str = "0.0.0.0", port: int = 8080) -> Any:
    if FastMCP is None:
        raise RuntimeError(
            "Missing dependency: 'mcp'. Install with: python3 -m pip install mcp"
        )

    mcp = FastMCP("dual-graph-mcp", host=host, port=port)

    @mcp.tool()
    def graph_retrieve(query: str, top_files: int = 5, top_edges: int = 12) -> dict[str, Any]:
        """Retrieve ranked files/edges using dual-graph first."""
        qk = _query_key(query)
        # New query starts a new adaptive turn budget.
        if qk and qk != TURN_STATE.get("query_key", ""):
            TURN_STATE["query_key"] = qk
            TURN_STATE["used_chars"] = 0
            TURN_STATE["seen_reads"] = {}
            TURN_STATE["reuse_gate_candidates"] = []
            TURN_STATE["reuse_gate_satisfied"] = False
            TURN_STATE["retrieved_files"] = []
            TURN_STATE["retrieve_count"] = 0
            TURN_STATE["last_retrieve_out"] = None
            TURN_STATE["fallback_calls"] = 0
        # Avoid repeated retrieval cycles for the same turn unless query changed.
        if ENFORCE_SINGLE_RETRIEVE and qk and qk == TURN_STATE.get("query_key", "") and int(TURN_STATE.get("retrieve_count", 0)) >= 1:
            cached = dict(TURN_STATE.get("last_retrieve_out") or {})
            if cached:
                cached["single_retrieve_reused"] = True
                return cached
        # Persistent retrieval cache (cross-turn) with safe invalidation.
        ck = _cache_key(query, top_files, top_edges)
        rcache = _load_retrieval_cache()
        cent = rcache.get("entries", {}).get(ck)
        if cent and _retrieval_entry_valid(cent):
            out = dict(cent.get("result", {}))
            out["retrieval_cache_hit"] = True
            out["retrieval_cache_key"] = ck
            TURN_STATE["retrieved_files"] = [str(f.get("id", "")) for f in out.get("graph_files", []) if str(f.get("id", ""))]
            TURN_STATE["last_retrieve_out"] = dict(out)
            TURN_STATE["retrieve_count"] = int(TURN_STATE.get("retrieve_count", 0)) + 1
            _log_tool("graph_retrieve", {"query": query, "top_files": top_files, "top_edges": top_edges, "mode": "retrieval_cache_hit"})
            _record_action("retrieve_cache_hit", {"query": query, "cache_key": ck})
            return out
        _log_tool("graph_retrieve", {"query": query, "top_files": top_files, "top_edges": top_edges})
        _record_action("retrieve", {"query": query, "top_files": top_files, "top_edges": top_edges})
        out = _local_chat_fix(query, top_files, top_edges) or _post(
            "/api/chat-fix",
            {"query": query, "top_files": top_files, "top_edges": top_edges, "max_grep_hits": 0},
        )
        # Action graph update + cache hints
        g = _load_action_graph()
        qid = f"query:{_query_key(query)}"
        _ensure_node(g, qid, "query", {"text": query})
        for f in out.get("graph_files", [])[: max(1, top_files)]:
            fid = str(f.get("id", ""))
            if not fid:
                continue
            _ensure_node(g, fid, "file")
            _add_edge(g, qid, fid, "retrieved")
        TURN_STATE["retrieved_files"] = [str(f.get("id", "")) for f in out.get("graph_files", [])[: max(1, top_files)] if str(f.get("id", ""))]
        _save_action_graph(g)

        files_meta = g.get("files", {})
        qterms = set(_query_terms(query))
        reuse: list[dict[str, Any]] = []
        for file, meta in files_meta.items():
            cached_terms = set(meta.get("query_terms", []))
            overlap = len(qterms & cached_terms)
            if overlap <= 0:
                continue
            reuse.append(
                {
                    "file": file,
                    "overlap": overlap,
                    "cached_chars": int(meta.get("cached_chars", 0)),
                    "cached_tokens_est": int(meta.get("cached_tokens_est", 0)),
                    "last_action": meta.get("last_action", ""),
                }
            )
        reuse.sort(key=lambda x: (-x["overlap"], -x["cached_tokens_est"], x["file"]))
        out["reuse_candidates"] = reuse[:3]
        TURN_STATE["reuse_gate_candidates"] = [r["file"] for r in reuse[:3]]
        TURN_STATE["reuse_gate_satisfied"] = False
        out["read_budget"] = {
            "remaining_chars": max(0, TURN_READ_BUDGET_CHARS - int(TURN_STATE.get("used_chars", 0))),
            "reuse_gate_candidates": TURN_STATE.get("reuse_gate_candidates", []),
        }
        TURN_STATE["retrieve_count"] = int(TURN_STATE.get("retrieve_count", 0)) + 1
        TURN_STATE["last_retrieve_out"] = dict(out)
        # Save retrieval cache with mtime stamps of returned files.
        rel_files = [str(f.get("id", "")) for f in out.get("graph_files", []) if str(f.get("id", ""))]
        mtimes: dict[str, int] = {}
        for rel in rel_files:
            # Symbol IDs (file::symbol) → stat the base file on disk.
            file_path = rel.split("::")[0] if "::" in rel else rel
            mtimes[rel] = _file_mtime_ns((PROJECT_ROOT / file_path).resolve())
        entries = rcache.get("entries", {})
        if not isinstance(entries, dict):
            entries = {}
        entries[ck] = {
            "created_epoch": int(datetime.now(timezone.utc).timestamp()),
            "files": rel_files,        # only file IDs, not full objects
            "mtimes_ns": mtimes,
            "result": out,
        }
        # Bound cache size to 50 entries (down from 200).
        if len(entries) > 50:
            items = sorted(entries.items(), key=lambda kv: int(kv[1].get("created_epoch", 0)))
            for old_key, _ in items[:-50]:
                entries.pop(old_key, None)
        rcache["entries"] = entries
        _save_retrieval_cache(rcache)
        return out

    @mcp.tool()
    def graph_read(file: str, max_chars: int = 4000, query: str = "", anchor: str = "") -> dict[str, Any]:
        """Read one file safely from project root with adaptive excerpting."""
        requested = max(256, int(max_chars or 0))
        max_chars = min(requested, HARD_MAX_READ_CHARS)
        qterms = _query_terms(query)
        # For file::symbol notation, also accept the base file in the allowlist.
        file_base = file.split("::")[0] if "::" in file else file
        retrieved_files = set(TURN_STATE.get("retrieved_files", []))
        if ENFORCE_READ_ALLOWLIST and retrieved_files and file not in retrieved_files and file_base not in retrieved_files:
            payload = {
                "file": file,
                "requested_chars": requested,
                "granted_chars": 0,
                "query": query,
                "anchor": anchor,
                "mode": "allowlist_blocked",
                "retrieved_files": sorted(retrieved_files),
            }
            _log_tool("graph_read", payload)
            _record_action("read_blocked_allowlist", payload)
            return {
                "ok": False,
                "error": "file not in retrieved allowlist; call graph_retrieve with broader top_files first",
                "retrieved_files": sorted(retrieved_files),
            }
        g = _load_action_graph()
        files_meta = g.setdefault("files", {})
        meta = files_meta.get(file, {})
        gate_candidates = list(TURN_STATE.get("reuse_gate_candidates", []))
        gate_satisfied = bool(TURN_STATE.get("reuse_gate_satisfied", False))
        if ENFORCE_REUSE_GATE and gate_candidates and not gate_satisfied and file not in gate_candidates and file_base not in gate_candidates:
            payload = {
                "file": file,
                "requested_chars": requested,
                "granted_chars": 0,
                "query": query,
                "anchor": anchor,
                "mode": "reuse_gate_blocked",
                "reuse_gate_candidates": gate_candidates,
            }
            _log_tool("graph_read", payload)
            _record_action("read_blocked_reuse_gate", payload)
            return {
                "ok": False,
                "error": "reuse gate active: read one reuse candidate first",
                "reuse_gate_candidates": gate_candidates,
            }
        # Cross-turn cache hit: reuse prior excerpt for same semantic query.
        if meta and set(meta.get("query_terms", [])) & set(qterms) and meta.get("cached_content"):
            cached = str(meta.get("cached_content", ""))[:max_chars]
            payload = {
                "file": file,
                "requested_chars": requested,
                "granted_chars": len(cached),
                "query": query,
                "anchor": anchor,
                "mode": "cache_hit",
                "response_chars": len(cached),
                "response_tokens_est": _est_tokens(cached),
            }
            _log_tool("graph_read", payload)
            _record_action("read_cache_hit", payload)
            if file in gate_candidates:
                TURN_STATE["reuse_gate_satisfied"] = True
            return {"ok": True, "file": file, "content": cached, "mode": "cache_hit", "from_action_graph": True}

        used = int(TURN_STATE.get("used_chars", 0))
        remaining = max(0, TURN_READ_BUDGET_CHARS - used)
        if remaining <= 0:
            payload = {
                "file": file,
                "requested_chars": requested,
                "granted_chars": 0,
                "query": query,
                "anchor": anchor,
                "mode": "budget_exhausted",
                "response_chars": 0,
                "response_tokens_est": 0,
            }
            _log_tool("graph_read", payload)
            return {
                "ok": False,
                "error": "turn read budget exhausted; call graph_retrieve again or use fallback_rg",
                "budget": {
                    "used_chars": used,
                    "remaining_chars": remaining,
                    "turn_read_budget_chars": TURN_READ_BUDGET_CHARS,
                },
            }

        granted = min(max_chars, remaining)
        dedupe_key = f"{file}|{_query_key(query)}|{anchor.lower()}"
        seen = TURN_STATE.get("seen_reads", {})
        if dedupe_key in seen:
            prev = str(seen[dedupe_key])
            # Return only tiny reminder for duplicate reads in same turn.
            preview = prev[:500]
            payload = {
                "file": file,
                "requested_chars": requested,
                "granted_chars": min(500, granted),
                "query": query,
                "anchor": anchor,
                "mode": "dedupe_preview",
                "response_chars": len(preview),
                "response_tokens_est": _est_tokens(preview),
            }
            _log_tool("graph_read", payload)
            return {"ok": True, "file": file, "content": preview, "mode": "dedupe_preview", "already_returned": True}

        # Handle file::symbol notation — O(1) lookup via symbol index.
        sym_meta = None
        file_for_fs = file
        if "::" in file:
            file_for_fs, _ = file.split("::", 1)
            sym_meta = _load_symbol_index().get(file)

        tgt = (PROJECT_ROOT / file_for_fs).resolve()
        if PROJECT_ROOT not in tgt.parents and tgt != PROJECT_ROOT:
            return {"ok": False, "error": "outside project root"}
        if not tgt.exists() or not tgt.is_file():
            # Remote/Railway mode: file is not on this server's disk.
            # Fall back to content uploaded with the graph.
            graph_json = DG_DATA_DIR / "info_graph.json"
            text = None
            if graph_json.exists():
                try:
                    gdata = json.loads(graph_json.read_text(encoding="utf-8"))
                    for node in gdata.get("nodes", []):
                        if node.get("path") == file_for_fs and node.get("content"):
                            text = node["content"]
                            break
                except Exception:
                    pass
            if not text:
                return {"ok": False, "error": "file not found", "file": file}
        else:
            text = tgt.read_text(encoding="utf-8", errors="ignore")
        mode = "full"
        sym_stale = False
        # If symbol notation matched, extract only the symbol's lines.
        if sym_meta:
            _lines = text.splitlines()
            _start = int(sym_meta.get("line_start", 0))
            _end = min(int(sym_meta.get("line_end", len(_lines) - 1)), len(_lines) - 1)
            text = "\n".join(_lines[_start:_end + 1])
            mode = "symbol_excerpt"
            # Staleness check: compare body hash against current file content.
            stored_hash = sym_meta.get("body_hash", "")
            if stored_hash:
                current_hash = hashlib.md5(text.encode()).hexdigest()[:8]
                sym_stale = current_hash != stored_hash
        if anchor:
            i = text.lower().find(anchor.lower())
            if i >= 0:
                start = max(0, i - granted // 2)
                end = min(len(text), i + granted // 2)
                text = text[start:end]
                mode = "anchor_excerpt"
            else:
                text = text[:granted]
                mode = "anchor_fallback_head"
        elif len(text) > granted:
            terms = _query_terms(query)
            text = _excerpt_by_terms(text, terms, granted)
            mode = "query_excerpt" if query else "head"
        TURN_STATE["used_chars"] = used + len(text)
        # Store only a 200-char fingerprint for dedupe — not the full content.
        seen[dedupe_key] = text[:200]
        if len(seen) > 20:  # evict oldest if too many entries
            oldest = next(iter(seen))
            del seen[oldest]
        TURN_STATE["seen_reads"] = seen
        payload = {
            "file": file,
            "requested_chars": requested,
            "granted_chars": granted,
            "query": query,
            "anchor": anchor,
            "mode": mode,
            "response_chars": len(text),
            "response_tokens_est": _est_tokens(text),
            "budget_used_chars": int(TURN_STATE.get("used_chars", 0)),
            "budget_remaining_chars": max(0, TURN_READ_BUDGET_CHARS - int(TURN_STATE.get("used_chars", 0))),
        }
        _log_tool("graph_read", payload)
        _record_action("read", payload)
        # Persist file cache + graph edges.
        qid = f"query:{_query_key(query)}" if query else "query:(empty)"
        _ensure_node(g, qid, "query", {"text": query})
        _ensure_node(g, file, "file")
        _add_edge(g, qid, file, "read", {"mode": mode})
        files_meta[file] = {
            "query_terms": qterms,
            "cached_content": text[:300],          # cap to 300 chars — just enough for context hints
            "cached_chars": len(text),
            "cached_tokens_est": _est_tokens(text),
            "last_action": "read",
            "last_ts": int(datetime.now(timezone.utc).timestamp()),
        }
        _save_action_graph(g)
        resp: dict[str, Any] = {"ok": True, "file": file, "content": text, "mode": mode}
        if sym_stale:
            resp["stale"] = True
            resp["stale_reason"] = "symbol body changed since last graph scan — consider running graph_scan again"
        return resp

    @mcp.tool()
    def graph_neighbors(file: str, limit: int = 30) -> dict[str, Any]:
        """Return graph edges touching a file."""
        _log_tool("graph_neighbors", {"file": file, "limit": limit})
        g = _local_info_graph() or _get("/api/info-graph?full=1")
        edges = g.get("edges", [])
        out = []
        for edge in edges:
            if edge.get("from") == file or edge.get("to") == file:
                out.append(edge)
            if len(out) >= limit:
                break
        return {"ok": True, "file": file, "neighbors": out}

    @mcp.tool()
    def graph_impact(changed_files: list[str]) -> dict[str, Any]:
        """Return connected local files likely impacted by edits."""
        _log_tool("graph_impact", {"changed_files": changed_files})
        _record_action("impact", {"changed_files": changed_files})
        g = _local_info_graph() or _get("/api/info-graph?full=1")
        edges = g.get("edges", [])
        changed = set(changed_files)
        connected: set[str] = set()
        for edge in edges:
            frm = str(edge.get("from", ""))
            to = str(edge.get("to", ""))
            if frm in changed and _is_local_file_ref(to):
                connected.add(to)
            if to in changed and _is_local_file_ref(frm):
                connected.add(frm)
        return {
            "ok": True,
            "changed_files": sorted(changed),
            "connected_files": sorted(connected),
            "untouched_connected_files": sorted(x for x in connected if x not in changed),
        }

    @mcp.tool()
    def graph_register_edit(files: list[str], summary: str = "") -> dict[str, Any]:
        """Register edited files into in-chat action graph memory."""
        g = _load_action_graph()
        aid = f"action:edit:{int(datetime.now(timezone.utc).timestamp())}"
        _ensure_node(g, aid, "action", {"summary": summary})
        files_meta = g.setdefault("files", {})
        for f in files:
            _ensure_node(g, f, "file")
            _add_edge(g, aid, f, "edited")
            meta = files_meta.get(f, {})
            meta["last_action"] = "edited"
            meta["last_ts"] = _now_iso()
            meta["edited_count"] = int(meta.get("edited_count", 0)) + 1
            files_meta[f] = meta
        _save_action_graph(g)
        payload = {"files": files, "summary": summary}
        invalidated = _invalidate_retrieval_cache_for_files(files)
        _log_tool("graph_register_edit", payload)
        _record_action("register_edit", {"files": files, "summary": summary, "retrieval_cache_invalidated": invalidated})
        return {"ok": True, "edited_files": files, "count": len(files), "retrieval_cache_invalidated": invalidated}

    @mcp.tool()
    def graph_action_summary(query: str = "", limit: int = 12) -> dict[str, Any]:
        """Return recent action graph summary + query-relevant touched files."""
        g = _load_action_graph()
        actions = g.get("actions", [])
        files_meta = g.get("files", {})
        recent = actions[-limit:]
        qterms = set(_query_terms(query))
        relevant = []
        for file, meta in files_meta.items():
            overlap = len(qterms & set(meta.get("query_terms", [])))
            if query and overlap <= 0:
                continue
            relevant.append(
                {
                    "file": file,
                    "overlap": overlap,
                    "last_action": meta.get("last_action", ""),
                    "edited_count": int(meta.get("edited_count", 0)),
                    "cached_tokens_est": int(meta.get("cached_tokens_est", 0)),
                    "last_ts": meta.get("last_ts", ""),
                }
            )
        relevant.sort(key=lambda x: (-x["overlap"], -x["edited_count"], -x["cached_tokens_est"], x["file"]))
        payload = {"query": query, "limit": limit}
        _log_tool("graph_action_summary", payload)
        _record_action("action_summary", payload)
        return {"ok": True, "recent_actions": recent, "relevant_files": relevant[:limit]}

    @mcp.tool()
    def graph_continue(query: str, top_files: int = 5, top_edges: int = 12, limit: int = 8) -> dict[str, Any]:
        """
        Continue a conversation using action-memory search first, then info-graph retrieval only if needed.
        Returns compact context hints instead of full chat dump.

        IMPORTANT — project setup check:
        If the response contains needs_project=True, no project has been scanned yet.
        You MUST:
          1. Ask the user: "Which directory should I scan? (default: current working directory)"
          2. Use their answer (or current working directory / pwd if they confirm the default).
          3. Call graph_scan(project_root=<path>) with that path.
          4. Then call graph_continue again to proceed with the original query.
        Do NOT attempt to answer the query until graph_scan has been called.
        """
        # ── Project setup gate ────────────────────────────────────────────────
        # Only check the graph file — NOT PROJECT_ROOT.is_dir().
        # In the Railway upload model the project directory never exists on the
        # server; the graph arrives via POST /ingest-graph, so the graph file
        # is the only reliable signal that the project has been scanned.
        graph_json = DG_DATA_DIR / "info_graph.json"
        graph_missing = not graph_json.exists()
        graph_empty = False
        gdata: dict[str, Any] = {}
        if not graph_missing:
            try:
                gdata = json.loads(graph_json.read_text(encoding="utf-8"))
                graph_empty = gdata.get("node_count", 0) == 0
            except Exception:
                graph_empty = True
        if graph_missing or graph_empty:
            gb_script = str(Path(__file__).resolve().parent / "graph_builder.py")
            ingest_url = f"{DG_BASE}/ingest-graph"
            return {
                "ok": False,
                "needs_project": True,
                "query": query,
                "graph_builder": gb_script,
                "ingest_url": ingest_url,
            }

        # Phase 0: Skip graph for small projects — not enough signal to be useful.
        file_count = gdata.get("file_count", gdata.get("node_count", 0))
        if file_count < 20:
            return {
                "ok": True,
                "skip": True,
                "file_count": file_count,
                "reason": "small project — explore directly without graph tools",
            }

        hist = _search_action_history(query, limit=limit)
        file_hits = hist.get("file_hits", [])
        action_hits = hist.get("action_hits", [])

        # If we already have relevant cached files from prior turns, prefer those first.
        if file_hits:
            rec = [f["file"] for f in file_hits[: min(3, len(file_hits))]]
            # Apply time-decay: files only recommended if touched in recent 5 actions.
            recent_files = {a.get("file", "") for a in action_hits}
            rec = [f for f in rec if f in recent_files] or rec
            out = {
                "ok": True,
                "mode": "memory_first",
                "confidence": "high",
                "max_supplementary_greps": 0,
                "max_supplementary_files": 0,
                "query": query,
                "recommended_files": rec,
            }
            _log_tool("graph_continue", {"query": query, "mode": "memory_first", "recommended_files": rec})
            _record_action("continue_memory_first", {"query": query, "recommended_files": rec})
            return out

        # No relevant memory: do single retrieval and return compact suggestions.
        retrieved = graph_retrieve(query=query, top_files=top_files, top_edges=top_edges)
        graph_files = retrieved.get("graph_files", [])
        rec_files = [str(f.get("id", "")) for f in graph_files if str(f.get("id", ""))]

        # ── Confidence tier based on top file score ───────────────────────────
        # Scores are integers from dg.score_node: 10+ = strong match, 4-9 = moderate, <4 = weak.
        top_score = int(graph_files[0].get("_score", 0)) if graph_files else 0
        if top_score >= 10:
            confidence = "high"
            max_supp_greps = 0
            max_supp_files = 0
        elif top_score >= 4:
            confidence = "medium"
            max_supp_greps = 2
            max_supp_files = 2
        else:
            confidence = "low"
            max_supp_greps = 3
            max_supp_files = 3

        out = {
            "ok": True,
            "mode": "retrieve_then_read",
            "confidence": confidence,
            "max_supplementary_greps": max_supp_greps,
            "max_supplementary_files": max_supp_files,
            "query": query,
            "recommended_files": rec_files[: min(3, len(rec_files))],
        }
        _log_tool("graph_continue", {"query": query, "mode": "retrieve_then_read", "confidence": confidence, "recommended_files": out["recommended_files"]})
        _record_action("continue_retrieve", {"query": query, "recommended_files": out["recommended_files"]})
        return out

    @mcp.tool()
    def fallback_rg(pattern: str, max_hits: int = 30) -> dict[str, Any]:
        """Controlled fallback grep if retriever confidence is low."""
        calls = int(TURN_STATE.get("fallback_calls", 0))
        if calls >= FALLBACK_MAX_CALLS_PER_TURN:
            payload = {
                "pattern": pattern,
                "max_hits": max_hits,
                "mode": "fallback_blocked_limit",
                "fallback_calls": calls,
                "fallback_max_calls": FALLBACK_MAX_CALLS_PER_TURN,
            }
            _log_tool("fallback_rg", payload)
            _record_action("fallback_blocked_limit", payload)
            return {
                "ok": False,
                "error": "fallback_rg call limit reached for this query turn",
                "fallback_calls": calls,
                "fallback_max_calls": FALLBACK_MAX_CALLS_PER_TURN,
            }
        _log_tool("fallback_rg", {"pattern": pattern, "max_hits": max_hits})
        cmd = ["rg", "-n", "-S", "--max-count", str(max_hits), pattern, "."]
        proc = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        hits = []
        for line in proc.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) == 3:
                hits.append({"file": parts[0], "line": parts[1], "text": parts[2]})
            if len(hits) >= max_hits:
                break
        TURN_STATE["fallback_calls"] = calls + 1
        return {"ok": True, "pattern": pattern, "hits": hits}

    @mcp.tool()
    def graph_scan(project_root: str) -> dict[str, Any]:
        """Scan a local project directory and build/refresh its information graph.

        Call this once at the start of a session to point the dual-graph at your
        project folder. After scanning, graph_retrieve / graph_read / graph_continue
        will work against that project.

        Args:
            project_root: Absolute path to the project directory to scan.
        """
        global PROJECT_ROOT  # noqa: PLW0603

        if _gb_scan is None:
            return {"ok": False, "error": "graph_builder not available"}

        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            return {"ok": False, "error": f"Not a directory: {root}"}

        graph = _gb_scan(root)

        # Write to the same JSON the dashboard serves.
        graph_json = DG_DATA_DIR / "info_graph.json"
        graph_json.parent.mkdir(parents=True, exist_ok=True)
        graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")

        # Build and persist symbol index for O(1) graph_read lookups.
        sym_index = _build_symbol_index(graph)
        SYMBOL_INDEX_FILE.write_text(json.dumps(sym_index), encoding="utf-8")

        # Update module-level root so graph_read / fallback_rg resolve correctly.
        PROJECT_ROOT = root

        # ── Reset all project-specific state ─────────────────────────────────
        # Retrieval cache: scores are stale from the old project.
        # Symbol index was already written above — do NOT delete it here.
        RETRIEVAL_CACHE_FILE.unlink(missing_ok=True)

        # Action graph: file reads/edits belong to the old project.
        _save_action_graph({"nodes": [], "edges": [], "files": {}, "actions": []})

        # Turn state: in-memory budgets, seen reads, retrieved file list.
        TURN_STATE.update({
            "query_key": "",
            "used_chars": 0,
            "seen_reads": {},
            "reuse_gate_candidates": [],
            "reuse_gate_satisfied": False,
            "retrieved_files": [],
            "retrieve_count": 0,
            "last_retrieve_out": None,
            "fallback_calls": 0,
        })

        file_count = graph.get("file_count", graph["node_count"])
        symbol_count = graph.get("symbol_count", 0)
        _log_tool("graph_scan", {"project_root": str(root), "files": file_count, "symbols": symbol_count, "edges": graph["edge_count"]})
        return {
            "ok": True,
            "project_root": str(root),
            "file_count": file_count,
            "symbol_count": symbol_count,
            "edge_count": graph["edge_count"],
            "message": "Graph built. Use graph_continue or graph_retrieve to query.",
        }

    return mcp


def main() -> int:
    import anyio
    import uvicorn
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    port = int(os.environ.get("PORT", 8080))
    DG_DATA_DIR.mkdir(parents=True, exist_ok=True)
    mcp = build_server(host="0.0.0.0", port=port)

    # Custom /ingest-graph route: accepts pre-built graph JSON from local machine
    # so users can run: graph_builder.py locally -> POST here -> chat via MCP
    async def ingest_graph(request: Request) -> JSONResponse:
        try:
            graph = await request.json()
            if "nodes" not in graph or "edges" not in graph:
                return JSONResponse({"ok": False, "error": "missing nodes/edges"}, status_code=400)
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        graph_json = DG_DATA_DIR / "info_graph.json"
        graph_json.parent.mkdir(parents=True, exist_ok=True)
        graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        # Build and persist symbol index for O(1) graph_read lookups.
        sym_index = _build_symbol_index(graph)
        SYMBOL_INDEX_FILE.write_text(json.dumps(sym_index), encoding="utf-8")
        # Invalidate retrieval cache so new graph is used immediately.
        RETRIEVAL_CACHE_FILE.unlink(missing_ok=True)
        return JSONResponse({
            "ok": True,
            "node_count": graph.get("node_count", len(graph["nodes"])),
            "edge_count": graph.get("edge_count", len(graph["edges"])),
        })

    # ── Static file routes: serve dg + graph_builder so users can curl-install ──
    _HERE = Path(__file__).resolve().parent

    async def serve_graph_builder(request: Request) -> Response:
        gb = _HERE / "graph_builder.py"
        return Response(gb.read_text(encoding="utf-8"), media_type="text/plain")

    async def serve_dg(request: Request) -> Response:
        return Response((_HERE / "dg").read_text(encoding="utf-8"), media_type="text/plain")

    async def serve_dgc(request: Request) -> Response:
        return Response((_HERE / "dgc").read_text(encoding="utf-8"), media_type="text/plain")

    async def serve_mcp_server(request: Request) -> Response:
        return Response((_HERE / "mcp_graph_server.py").read_text(encoding="utf-8"), media_type="text/plain")

    async def serve_install(request: Request) -> Response:
        base = str(request.base_url).rstrip("/")
        script = f"""\
#!/usr/bin/env bash
set -euo pipefail
BASE_URL="{base}"
INSTALL_DIR="$HOME/.dual-graph"
mkdir -p "$INSTALL_DIR"

echo "[install] Downloading files..."
curl -sSL "$BASE_URL/graph_builder.py"    -o "$INSTALL_DIR/graph_builder.py"
curl -sSL "$BASE_URL/mcp_graph_server.py" -o "$INSTALL_DIR/mcp_graph_server.py"
curl -sSL "$BASE_URL/dg"  -o "$INSTALL_DIR/dg"  && chmod +x "$INSTALL_DIR/dg"
curl -sSL "$BASE_URL/dgc" -o "$INSTALL_DIR/dgc" && chmod +x "$INSTALL_DIR/dgc"

echo "[install] Installing Python dependencies..."
python3 -m pip install "mcp>=1.3.0" uvicorn anyio starlette --quiet

# Add to PATH if not already there
SHELL_RC="$HOME/.zshrc"
[[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"
if ! grep -q '.dual-graph' "$SHELL_RC" 2>/dev/null; then
  echo 'export PATH="$PATH:$HOME/.dual-graph"' >> "$SHELL_RC"
  echo "[install] Added ~/.dual-graph to PATH in $SHELL_RC"
fi

echo ""
echo "[install] Done! Run these once:"
echo "  source $SHELL_RC"
echo ""
echo "  # Register for Codex CLI (uses Railway):"
echo "  codex mcp add dual-graph --url $BASE_URL/mcp"
echo ""
echo "  # Register for Claude Code (uses local server):"
echo "  claude mcp add --transport http dual-graph http://localhost:8080/mcp"
echo ""
echo "Then per project:"
echo "  dg /path/to/project    # Codex CLI  (Railway MCP)"
echo "  dgc /path/to/project   # Claude Code (local MCP, fully private)"
"""
        return Response(script, media_type="text/plain")

    # Get the MCP app with its lifespan (session manager) intact.
    # IMPORTANT: do NOT wrap mcp_app in a new Starlette app via Mount("/") —
    # that kills the inner lifespan so the session manager never starts,
    # causing every /mcp request to return HTTP 500.
    # Instead, prepend our custom routes directly into mcp_app's own router
    # so it remains the top-level ASGI app and its lifespan runs normally.
    mcp_app = mcp.streamable_http_app()
    mcp_app.router.routes[0:0] = [
        Route("/ingest-graph", ingest_graph, methods=["POST"]),
        Route("/install.sh", serve_install, methods=["GET"]),
        Route("/dgc", serve_dgc, methods=["GET"]),
        Route("/dg", serve_dg, methods=["GET"]),
        Route("/graph_builder.py", serve_graph_builder, methods=["GET"]),
        Route("/mcp_graph_server.py", serve_mcp_server, methods=["GET"]),
    ]

    async def serve() -> None:
        config = uvicorn.Config(mcp_app, host="0.0.0.0", port=port, log_level="error")
        await uvicorn.Server(config).serve()

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
