#!/usr/bin/env python3
"""MCP gateway exposing dual-graph retrieval/read/impact tools."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
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


DG_BASE = os.environ.get("DG_BASE_URL", "http://127.0.0.1:8787")
DG_API_TOKEN = os.environ.get("DG_API_TOKEN", "").strip()
PROJECT_ROOT = Path(
    os.environ.get(
        "DUAL_GRAPH_PROJECT_ROOT",
        "/app/project",  # default clone target in Railway (set via GITHUB_REPO_URL)
    )
).resolve()
LOG_FILE = Path(__file__).resolve().parent / "data" / "mcp_tool_calls.jsonl"
ACTION_GRAPH_FILE = Path(__file__).resolve().parent / "data" / "chat_action_graph.json"
RETRIEVAL_CACHE_FILE = Path(__file__).resolve().parent / "data" / "retrieval_cache.json"
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


def _is_local_file_ref(value: str) -> bool:
    if not value:
        return False
    if value.startswith("@") or ":" in value:
        return False
    if "/" not in value:
        return False
    return "." in value.split("/")[-1]


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
        p = (PROJECT_ROOT / rel).resolve()
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
    kill_keys = []
    for key, ent in entries.items():
        files = ent.get("files", [])
        if not isinstance(files, list):
            continue
        if any(f in changed for f in files):
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
        out = _post(
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
        out["reuse_candidates"] = reuse[:8]
        TURN_STATE["reuse_gate_candidates"] = [r["file"] for r in reuse[:3]]
        TURN_STATE["reuse_gate_satisfied"] = False
        out["read_budget"] = {
            "hard_max_read_chars": HARD_MAX_READ_CHARS,
            "turn_read_budget_chars": TURN_READ_BUDGET_CHARS,
            "used_chars": int(TURN_STATE.get("used_chars", 0)),
            "remaining_chars": max(0, TURN_READ_BUDGET_CHARS - int(TURN_STATE.get("used_chars", 0))),
            "reuse_gate_enabled": ENFORCE_REUSE_GATE,
            "reuse_gate_candidates": TURN_STATE.get("reuse_gate_candidates", []),
            "reuse_gate_satisfied": bool(TURN_STATE.get("reuse_gate_satisfied", False)),
            "single_retrieve_enabled": ENFORCE_SINGLE_RETRIEVE,
            "retrieve_count": int(TURN_STATE.get("retrieve_count", 0)),
            "fallback_calls": int(TURN_STATE.get("fallback_calls", 0)),
            "fallback_max_calls": FALLBACK_MAX_CALLS_PER_TURN,
        }
        TURN_STATE["retrieve_count"] = int(TURN_STATE.get("retrieve_count", 0)) + 1
        TURN_STATE["last_retrieve_out"] = dict(out)
        # Save retrieval cache with mtime stamps of returned files.
        rel_files = [str(f.get("id", "")) for f in out.get("graph_files", []) if str(f.get("id", ""))]
        mtimes: dict[str, int] = {}
        for rel in rel_files:
            mtimes[rel] = _file_mtime_ns((PROJECT_ROOT / rel).resolve())
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
        retrieved_files = set(TURN_STATE.get("retrieved_files", []))
        if ENFORCE_READ_ALLOWLIST and retrieved_files and file not in retrieved_files:
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
        if ENFORCE_REUSE_GATE and gate_candidates and not gate_satisfied and file not in gate_candidates:
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

        tgt = (PROJECT_ROOT / file).resolve()
        if PROJECT_ROOT not in tgt.parents and tgt != PROJECT_ROOT:
            return {"ok": False, "error": "outside project root"}
        if not tgt.exists() or not tgt.is_file():
            return {"ok": False, "error": "file not found", "file": file}
        text = tgt.read_text(encoding="utf-8", errors="ignore")
        mode = "full"
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
        return {"ok": True, "file": file, "content": text, "mode": mode}

    @mcp.tool()
    def graph_neighbors(file: str, limit: int = 30) -> dict[str, Any]:
        """Return graph edges touching a file."""
        _log_tool("graph_neighbors", {"file": file, "limit": limit})
        g = _get("/api/info-graph?full=1")
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
        g = _get("/api/info-graph?full=1")
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
        graph_json = Path(__file__).resolve().parent / "data" / "info_graph.json"
        project_missing = not PROJECT_ROOT.is_dir()
        graph_missing = not graph_json.exists()
        graph_empty = False
        if not graph_missing:
            try:
                graph_empty = json.loads(graph_json.read_text(encoding="utf-8")).get("node_count", 0) == 0
            except Exception:
                graph_empty = True
        if project_missing or graph_missing or graph_empty:
            gb_script = str(Path(__file__).resolve().parent / "graph_builder.py")
            ingest_url = f"{DG_BASE}/ingest-graph"
            return {
                "ok": False,
                "needs_project": True,
                "query": query,
                "graph_builder": gb_script,
                "ingest_url": ingest_url,
                "instruction": (
                    "No project scanned yet. Do these steps in order:\n"
                    "1. Ask the user: 'Which directory should I scan? (default: current working directory)'\n"
                    "2. If they say 'current' or press Enter, run `pwd` to get the path.\n"
                    "3. Build the graph locally by running this shell command:\n"
                    f"   python3 {gb_script} --root <project_path> --out /tmp/dg_graph.json\n"
                    "4. Upload it to the server:\n"
                    f"   curl -s -X POST {ingest_url} -H 'Content-Type: application/json' --data-binary @/tmp/dg_graph.json\n"
                    "5. Call graph_continue again with the original query."
                ),
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
                "query": query,
                "recommended_files": rec,
                "instruction": "Use graph_read on recommended_files first; avoid new retrieval unless insufficient.",
            }
            _log_tool("graph_continue", {"query": query, "mode": "memory_first", "recommended_files": rec})
            _record_action("continue_memory_first", {"query": query, "recommended_files": rec})
            return out

        # No relevant memory: do single retrieval and return compact suggestions.
        retrieved = graph_retrieve(query=query, top_files=top_files, top_edges=top_edges)
        rec_files = [str(f.get("id", "")) for f in retrieved.get("graph_files", []) if str(f.get("id", ""))]
        out = {
            "ok": True,
            "mode": "retrieve_then_read",
            "query": query,
            "recommended_files": rec_files[: min(3, len(rec_files))],
            "instruction": "Use graph_read on recommended_files; do not dump full chat history.",
        }
        _log_tool("graph_continue", {"query": query, "mode": "retrieve_then_read", "recommended_files": out["recommended_files"]})
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
        graph_json = Path(__file__).resolve().parent / "data" / "info_graph.json"
        graph_json.parent.mkdir(parents=True, exist_ok=True)
        graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")

        # Update module-level root so graph_read / fallback_rg resolve correctly.
        PROJECT_ROOT = root

        # ── Reset all project-specific state ─────────────────────────────────
        # Retrieval cache: stale file scores from old project.
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

        _log_tool("graph_scan", {"project_root": str(root), "nodes": graph["node_count"], "edges": graph["edge_count"]})
        return {
            "ok": True,
            "project_root": str(root),
            "node_count": graph["node_count"],
            "edge_count": graph["edge_count"],
            "message": "Graph built. Action graph and caches reset. Use graph_continue or graph_retrieve to query.",
        }

    return mcp


def main() -> int:
    import anyio
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Mount, Route

    port = int(os.environ.get("PORT", 8080))
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
        graph_json = Path(__file__).resolve().parent / "data" / "info_graph.json"
        graph_json.parent.mkdir(parents=True, exist_ok=True)
        graph_json.write_text(json.dumps(graph, indent=2), encoding="utf-8")
        # Invalidate retrieval cache so new graph is used immediately.
        RETRIEVAL_CACHE_FILE.unlink(missing_ok=True)
        return JSONResponse({
            "ok": True,
            "node_count": graph.get("node_count", len(graph["nodes"])),
            "edge_count": graph.get("edge_count", len(graph["edges"])),
        })

    mcp_app = mcp.streamable_http_app()
    app = Starlette(routes=[
        Route("/ingest-graph", ingest_graph, methods=["POST"]),
        Mount("/", app=mcp_app),
    ])

    async def serve() -> None:
        config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
        await uvicorn.Server(config).serve()

    anyio.run(serve)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
