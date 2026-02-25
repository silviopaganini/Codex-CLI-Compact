#!/usr/bin/env python3
"""Dual-graph starter CLI for Claude Code style hook integration."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from graph_builder import scan


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
GRAPH_JSON = DATA_DIR / "info_graph.json"
ACTION_LOG = DATA_DIR / "action_events.jsonl"
TOKEN_LOG = DATA_DIR / "token_usage.jsonl"
CAPABILITY_INDEX = Path(os.environ.get("DG_CAPABILITY_INDEX", str(DATA_DIR / "functionality_index.md"))).resolve()
DEFAULT_ROOT = Path(
    os.environ.get(
        "DUAL_GRAPH_PROJECT_ROOT",
        "/Users/krishnakant/documents/personal projects/restaurant CRM/restaurant-crm",
    )
).resolve()


@dataclass
class RetrieveResult:
    files: list[dict]
    edges: list[dict]


@dataclass
class CapabilityEntry:
    name: str
    keywords: list[str]
    files: list[str]


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_graph() -> dict:
    if not GRAPH_JSON.exists():
        g = scan(DEFAULT_ROOT)
        ensure_data_dir()
        GRAPH_JSON.write_text(json.dumps(g, indent=2), encoding="utf-8")
        return g
    return json.loads(GRAPH_JSON.read_text(encoding="utf-8"))


def extract_route(query: str) -> tuple[str, list[str]]:
    """
    Pull out an explicit HTTP route from the query if present.
    Returns (method, [path_segments]) or ("", []).
    e.g. "POST /api/invoice/create" → ("POST", ["invoice", "create"])
    Note: "api" is intentionally dropped — it is in every path and adds noise.
    """
    m = re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\s+(/[\w/\-{}:]+)", query, re.IGNORECASE)
    if not m:
        return "", []
    method = m.group(1).upper()
    raw_segs = [re.sub(r"[{}:<>]", "", s) for s in m.group(2).strip("/").split("/")]
    segs = [s.lower() for s in raw_segs if s and s.lower() != "api"]
    return method, segs


def tokenize_query(text: str) -> list[str]:
    stop = {
        "a", "an", "the", "to", "for", "with", "from", "and", "or", "of", "on", "in", "by",
        "you", "your", "can", "could", "should", "would", "will", "want", "need", "please",
        "fix", "update", "make", "show", "differently", "different", "change", "do", "it",
        # "api" is in nearly every backend path — matching on it is pure noise.
        "api",
    }
    words = [w for w in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(w) >= 2]
    out = []
    seen = set()
    for w in words:
        if w in stop:
            continue
        if w in seen:
            continue
        seen.add(w)
        out.append(w)
    return out


def score_text(text: str, terms: list[str]) -> int:
    blob = text.lower()
    score = 0
    for term in terms:
        if term in blob:
            score += 1
    return score


def classify_intent(query: str) -> str:
    q = query.lower()
    # Explicit HTTP route → treat as a targeted debug/edit regardless of other words.
    if re.search(r"\b(GET|POST|PUT|DELETE|PATCH)\s+/\S+", query, re.IGNORECASE):
        return "debug"
    if any(k in q for k in ("why", "explain", "architecture", "dependency", "how does")):
        return "explain"
    if any(k in q for k in ("error", "bug", "crash", "failing", "fail", "broken", "stack trace",
                             "500", "404", "returning", "throws", "exception")):
        return "debug"
    if any(k in q for k in ("test", "unit test", "integration test", "coverage")):
        return "test"
    if any(k in q for k in ("refactor", "cleanup", "simplify", "restructure", "optimize")):
        return "refactor"
    if any(k in q for k in ("add", "create", "implement", "build", "support")):
        return "feature"
    if any(k in q for k in ("fix", "update", "change", "edit", "modify", "patch")):
        return "edit"
    return "general"


def node_role(path: str, ext: str) -> str:
    p = path.lower()
    if ext == ".md":
        return "docs"
    if "/test/" in p or "/tests/" in p or p.endswith(".test.ts") or p.endswith(".spec.ts") or p.endswith(".test.tsx") or p.endswith(".spec.tsx"):
        return "test"
    if "/components/ui/" in p:
        return "shared_ui"
    if any(k in p for k in ("/pages/", "/components/features/", "/views/", "/screens/")):
        return "ui_surface"
    if any(k in p for k in ("/api/", "/services/", "/store/", "/hooks/", "/utils/")):
        return "logic"
    return "code"


def intent_role_weight(intent: str, role: str) -> int:
    table = {
        "edit": {"ui_surface": 3, "logic": 3, "shared_ui": 1, "code": 2, "docs": -2, "test": 1},
        "feature": {"ui_surface": 3, "logic": 4, "shared_ui": 1, "code": 2, "docs": -2, "test": 1},
        "debug": {"ui_surface": 2, "logic": 4, "shared_ui": 0, "code": 2, "docs": -2, "test": 2},
        "refactor": {"ui_surface": 2, "logic": 3, "shared_ui": 1, "code": 3, "docs": -2, "test": 2},
        "test": {"ui_surface": 1, "logic": 2, "shared_ui": 0, "code": 1, "docs": -2, "test": 5},
        "explain": {"ui_surface": 1, "logic": 2, "shared_ui": 0, "code": 1, "docs": 2, "test": 0},
        "general": {"ui_surface": 2, "logic": 2, "shared_ui": 0, "code": 1, "docs": -1, "test": 0},
    }
    return table.get(intent, table["general"]).get(role, 0)


def query_scoped_to_feature(q: str) -> bool:
    # Scoped requests usually target a product area, not a global design-system change.
    return any(k in q for k in ("portal", "checkout", "invoice", "payment", "order", "restaurant", "customer", "admin"))


def score_node(node: dict, terms: list[str], query: str) -> int:
    path = str(node.get("id", "")).lower()
    ext = str(node.get("ext", "")).lower()
    intent = classify_intent(query)
    role = node_role(path, ext)
    q = query.lower()
    keywords: list[str] = node.get("keywords", [])
    route_method, route_segs = extract_route(query)

    score = score_text(path, terms) * 3
    # Structural keyword match: function names, class names, route segments stored at scan time.
    # Weight 2 (less than path × 3 for exact hits, but rescues misnamed files).
    if keywords:
        kw_blob = " ".join(keywords)
        score += score_text(kw_blob, terms) * 2
    # Route-specific boost: if query mentions "POST /api/invoice/create", boost files
    # whose keywords contain those route segments or whose path matches them.
    if route_segs:
        seg_blob = " ".join(keywords) + " " + path
        matches = sum(1 for seg in route_segs if seg in seg_blob)
        score += matches * 4
        if route_method and route_method.lower() in " ".join(keywords):
            score += 3

    score += intent_role_weight(intent, role)

    # Prefer code files for fixes.
    if ext in {".py", ".ts", ".tsx", ".js", ".jsx", ".go"}:
        score += 4
    elif ext == ".md":
        score -= 2

    # Penalize generated/noisy areas.
    if any(bad in path for bad in ("node_modules/", "site-packages/", "/venv/", "/.venv/")):
        score -= 10

    # Prefer feature-level files over shared primitives by default.
    if "/components/ui/" in path:
        score -= 1
    if "/components/features/" in path or "/pages/" in path or "/api/" in path:
        score += 2

    # Portal focus boost: keep query-local portal first.
    if "restaurant" in q and "restaurant-portal/" in path:
        score += 4
    if "customer" in q and "customer-portal/" in path:
        score += 4
    if "admin" in q and "admin-portal/" in path:
        score += 4

    # Payment-related emphasis.
    if any(k in q for k in ("payment", "invoice", "checkout")) and any(k in path for k in ("payment", "invoice", "checkout", "order")):
        score += 3

    # UI-targeted queries should prioritize concrete surfaces (cards/modals/pages) over shared primitives.
    if any(k in q for k in ("button", "modal", "card", "table", "form", "badge", "page", "screen")):
        if role == "ui_surface":
            score += 4
        if any(k in path for k in ("card", "modal", "details", "list", "table", "orders", "checkout")):
            score += 3
        # For behavior changes, prefer concrete interaction surfaces over listing shells.
        if "button" in q and any(k in q for k in ("status", "payment", "checkout", "invoice")):
            if any(k in path for k in ("card", "modal", "detail")):
                score += 4
            if any(k in path for k in ("list", "table", "/pages/")):
                score -= 3
        if "/components/ui/" in path and query_scoped_to_feature(q) and not any(k in q for k in ("global", "shared", "design system", "reusable")):
            score -= 2

    # Docs are helpful for explain tasks but usually noise for edit/debug/feature tasks.
    if role == "docs" and intent in {"edit", "feature", "debug", "refactor"}:
        score -= 3

    # Symbol nodes are more precise than file nodes — boost them so they surface above
    # their parent files when the query matches a specific function/class/hook.
    if node.get("kind") == "symbol":
        score += 3
        if node.get("confidence") == "high":
            score += 2

    return score


def load_capability_index(path: Path) -> list[CapabilityEntry]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    out: list[CapabilityEntry] = []
    cur_name = ""
    cur_keywords: list[str] = []
    cur_files: list[str] = []

    def flush() -> None:
        nonlocal cur_name, cur_keywords, cur_files
        if cur_name and (cur_keywords or cur_files):
            out.append(CapabilityEntry(name=cur_name, keywords=cur_keywords, files=cur_files))
        cur_name = ""
        cur_keywords = []
        cur_files = []

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("## "):
            flush()
            cur_name = line[3:].strip()
            continue
        if line.lower().startswith("keywords:"):
            kw = line.split(":", 1)[1]
            cur_keywords = [k.strip().lower() for k in kw.split(",") if k.strip()]
            continue
        # Any bullet that looks like a file path is accepted.
        if line.startswith("- "):
            v = line[2:].strip().strip("`")
            if "/" in v and "." in v:
                cur_files.append(v)
            continue

    flush()
    return out


def capability_file_boosts(query_terms: list[str], caps: list[CapabilityEntry]) -> dict[str, int]:
    boosts: dict[str, int] = {}
    q = set(query_terms)
    for cap in caps:
        kw = set(k.lower() for k in cap.keywords)
        overlap = len(q & kw)
        if overlap <= 0:
            continue
        # Stronger overlap => stronger boost.
        base = 4 + overlap * 2
        for f in cap.files:
            boosts[f] = max(boosts.get(f, 0), base)
    return boosts


def retrieve(graph: dict, query: str, top_files: int, top_edges: int) -> RetrieveResult:
    terms = tokenize_query(query)
    intent = classify_intent(query)
    q = query.lower()
    caps = load_capability_index(CAPABILITY_INDEX)
    cap_boost = capability_file_boosts(terms, caps)
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    degree: Counter[str] = Counter()
    button_consumers: set[str] = set()
    badge_consumers: set[str] = set()
    for e in edges:
        frm = str(e.get("from", ""))
        to = str(e.get("to", ""))
        rel = str(e.get("rel", ""))
        if frm:
            degree[frm] += 1
        if to:
            degree[to] += 1
        if rel == "imports":
            to_l = to.lower()
            if "button" in to_l:
                button_consumers.add(frm)
            if "badge" in to_l:
                badge_consumers.add(frm)

    node_scored: list[tuple[int, dict]] = []
    for node in nodes:
        s = score_node(node, terms, query)
        node_id = str(node.get("id", ""))
        # Exact path boost from capability index.
        s += cap_boost.get(node_id, 0)
        # Prefix support: capability path ending with "/" or "*" boosts subtree.
        for pref, b in cap_boost.items():
            if pref.endswith("/") and node_id.startswith(pref):
                s += b
            elif pref.endswith("*") and node_id.startswith(pref[:-1]):
                s += b
        # Slight preference for files connected in the graph (often higher impact).
        s += min(4, degree.get(node_id, 0) // 3)
        # Query-aligned import-aware weighting.
        if "button" in q and node_id in button_consumers:
            s += 6
        if "button" in q and "badge" not in q and node_id in badge_consumers:
            s -= 2
        if "badge" in q and node_id in badge_consumers:
            s += 4
        if s > 0:
            node_scored.append((s, node))
    node_scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    # Deduplicate: if a symbol from file F is included, skip the file node F,
    # and vice-versa. Whatever scores highest wins — file or symbol — but only
    # one representative per file is allowed in the top results.
    chosen_files = []
    seen_file_bases: set[str] = set()
    for s, n in node_scored:
        if len(chosen_files) >= top_files:
            break
        node_id = str(n.get("id", ""))
        kind = str(n.get("kind", "file"))
        if kind == "symbol":
            base = node_id.split("::")[0] if "::" in node_id else node_id
            if base in seen_file_bases:
                continue  # file (or another symbol from it) already chosen
            seen_file_bases.add(base)
        else:
            if node_id in seen_file_bases:
                continue  # a symbol from this file scored higher — skip the file node
            seen_file_bases.add(node_id)
        # Strip content — file content must come via graph_read, not retrieve.
        row = {k: v for k, v in n.items() if k != "content"}
        row["_score"] = s
        row["_role"] = node_role(str(row.get("id", "")), str(row.get("ext", "")))
        row["_intent"] = intent
        chosen_files.append(row)
    chosen_ids = {n.get("id", "") for n in chosen_files}

    edge_scored: list[tuple[int, dict]] = []
    for edge in edges:
        rel = str(edge.get("rel", ""))
        blob = f"{edge.get('from', '')} {rel} {edge.get('to', '')}"
        s = score_text(blob, terms) * 2
        if edge.get("from") in chosen_ids or edge.get("to") in chosen_ids:
            s += 4
        if edge.get("from") in cap_boost or edge.get("to") in cap_boost:
            s += 2
        if rel == "imports":
            s += 1
        if s > 0:
            edge_scored.append((s, edge))
    edge_scored.sort(key=lambda x: (-x[0], x[1].get("from", ""), x[1].get("to", "")))
    chosen_edges = [e for _, e in edge_scored[:top_edges]]

    # If query doesn't match much, provide top project-local edges and files as fallback.
    if not chosen_files:
        chosen_files = nodes[:top_files]
    if not chosen_edges:
        chosen_edges = edges[:top_edges]

    return RetrieveResult(files=chosen_files, edges=chosen_edges)


def read_action_events(limit: int = 8) -> list[dict]:
    if not ACTION_LOG.exists():
        return []
    rows: list[dict] = []
    for line in ACTION_LOG.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def cmd_scan(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    g = scan(root)
    ensure_data_dir()
    out = Path(args.out).resolve() if args.out else GRAPH_JSON
    out.write_text(json.dumps(g, indent=2), encoding="utf-8")
    print(f"Scanned: {g['node_count']} nodes, {g['edge_count']} edges")
    print(f"Wrote: {out}")
    return 0


def cmd_retrieve(args: argparse.Namespace) -> int:
    g = load_graph()
    result = retrieve(g, args.query, args.top_files, args.top_edges)
    payload = {
        "query": args.query,
        "files": result.files,
        "edges": result.edges,
    }
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Query: {args.query}\n")
    print("Relevant files:")
    for f in result.files:
        print(f"- {f.get('id')}")
    print("\nRelevant relations:")
    for e in result.edges:
        print(f"- {e.get('from')} --{e.get('rel')}--> {e.get('to')}")
    return 0


def cmd_prime(args: argparse.Namespace) -> int:
    g = load_graph()
    query = args.query or os.environ.get("DG_QUERY", "General codebase maintenance task")
    result = retrieve(g, query, args.top_files, args.top_edges)
    actions = read_action_events(limit=args.recent_actions)

    print("# Dual Graph Active\n")
    print("## Rules")
    print("- Prefer focused context over full transcript dumps.")
    print("- Use graph-backed files/edges for impact analysis.")
    print("- Preserve existing behavior unless request says otherwise.\n")

    print("## Current Focus")
    print(f"- Query: {query}\n")

    print(f"## Relevant Files (Top {len(result.files)})")
    for f in result.files:
        print(f"- {f.get('id')}")
    print()

    print(f"## Relevant Relations (Top {len(result.edges)})")
    for e in result.edges:
        print(f"- {e.get('from')} --{e.get('rel')}--> {e.get('to')}")
    print()

    print(f"## Action Trail (Recent {len(actions)})")
    if not actions:
        print("- (no actions recorded yet)")
    for ev in actions:
        kind = ev.get("kind", "unknown")
        summary = ev.get("summary", "")
        print(f"- [{kind}] {summary}")
    return 0


def cmd_action_log(args: argparse.Namespace) -> int:
    ensure_data_dir()
    meta: dict = {}
    if args.meta:
        try:
            meta = json.loads(args.meta)
            if not isinstance(meta, dict):
                raise ValueError("meta must be a JSON object")
        except Exception as e:  # noqa: BLE001
            print(f"error: invalid --meta JSON: {e}", file=sys.stderr)
            return 2

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": args.kind,
        "summary": args.summary or "",
        "meta": meta,
    }
    with ACTION_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    print("ok")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    events: list[dict] = []
    if TOKEN_LOG.exists():
        for line in TOKEN_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    by_mode = Counter()
    total = 0
    for ev in events:
        t = int(ev.get("total_tokens", 0))
        total += t
        by_mode[str(ev.get("mode", "unknown"))] += t

    payload = {
        "event_count": len(events),
        "total_tokens": total,
        "by_mode": dict(by_mode),
        "recent": events[-20:],
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Events: {payload['event_count']}")
        print(f"Total tokens: {payload['total_tokens']}")
        for mode, count in sorted(payload["by_mode"].items()):
            print(f"- {mode}: {count}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Dual-graph starter CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    scan_p = sub.add_parser("scan", help="Scan project and build info graph")
    scan_p.add_argument("--root", default=str(DEFAULT_ROOT), help="Project root to scan")
    scan_p.add_argument("--out", default=str(GRAPH_JSON), help="Output graph JSON")
    scan_p.set_defaults(func=cmd_scan)

    retrieve_p = sub.add_parser("retrieve", help="Retrieve relevant files/edges for a query")
    retrieve_p.add_argument("--query", required=True, help="Natural language task/query")
    retrieve_p.add_argument("--top-files", type=int, default=20)
    retrieve_p.add_argument("--top-edges", type=int, default=40)
    retrieve_p.add_argument("--json", action="store_true")
    retrieve_p.set_defaults(func=cmd_retrieve)

    prime_p = sub.add_parser("prime", help="Output compact context for Claude hooks")
    prime_p.add_argument("--query", default="", help="Current query/task")
    prime_p.add_argument("--top-files", type=int, default=12)
    prime_p.add_argument("--top-edges", type=int, default=20)
    prime_p.add_argument("--recent-actions", type=int, default=8)
    prime_p.set_defaults(func=cmd_prime)

    action_p = sub.add_parser("action", help="Action graph operations")
    action_sub = action_p.add_subparsers(dest="action_cmd", required=True)
    action_log_p = action_sub.add_parser("log", help="Append action event")
    action_log_p.add_argument("--kind", required=True, help="Action kind")
    action_log_p.add_argument("--summary", default="", help="Short action summary")
    action_log_p.add_argument("--meta", default="", help="JSON object metadata")
    action_log_p.set_defaults(func=cmd_action_log)

    stats_p = sub.add_parser("stats", help="Token usage stats")
    stats_p.add_argument("--json", action="store_true")
    stats_p.set_defaults(func=cmd_stats)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
