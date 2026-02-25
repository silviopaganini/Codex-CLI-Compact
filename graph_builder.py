#!/usr/bin/env python3
"""Build a lightweight information graph by scanning project files.

Phase 1: Adds symbol-level nodes (functions, API routes, hooks, models)
with line ranges and content hashes for precise graph_read calls.
graph_read("src/auth.ts::handleLogin") reads only those lines, not the full file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git", ".beads", ".beads-hooks", "node_modules", "vendor",
    "dist", "build", ".next", ".idea", ".vscode", "__pycache__",
    "venv", ".venv", ".dual-graph",
}

MAX_FILE_BYTES = 300_000
MAX_CONTENT_CHARS = 24_000

# Only extract symbols from code files (not config/markdown)
SYMBOL_EXTS = {".ts", ".tsx", ".js", ".jsx", ".py"}


@dataclass
class Node:
    id: str
    kind: str       # "file" or "symbol"
    path: str       # relative file path (for symbols: the containing file)
    ext: str
    size: int
    keywords: list[str]
    content: str = ""
    # Symbol-only fields
    symbol_type: str = ""   # api_route | hook | model | use_case | utility
    name: str = ""
    line_start: int = 0
    line_end: int = 0
    body_hash: str = ""
    confidence: str = ""    # high | medium | low
    exported: bool = False

    def as_dict(self) -> dict:
        d = {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "ext": self.ext,
            "size": self.size,
            "keywords": self.keywords,
        }
        if self.kind == "file":
            d["content"] = self.content
        else:
            d["symbol_type"] = self.symbol_type
            d["name"] = self.name
            d["line_start"] = self.line_start
            d["line_end"] = self.line_end
            d["body_hash"] = self.body_hash
            d["confidence"] = self.confidence
            d["exported"] = self.exported
        return d


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split_camel(name: str) -> list[str]:
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    return [p.lower() for p in parts.split() if len(p) >= 3]


def _name_keywords(name: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()
    def add(w: str) -> None:
        w = w.lower().strip("_")
        if len(w) >= 3 and w not in seen:
            seen.add(w); tokens.append(w)
    add(name)
    for p in _split_camel(name):
        add(p)
    for p in name.split("_"):
        add(p)
    return tokens[:10]


def _body_hash(lines: list[str], start: int, end: int) -> str:
    body = "\n".join(lines[start : end + 1])
    return hashlib.md5(body.encode()).hexdigest()[:8]


def _find_block_end_ts(lines: list[str], start: int) -> int:
    """Find closing brace of a TS/JS block starting at `start` via brace counting."""
    depth = 0
    found_open = False
    limit = min(start + 400, len(lines))
    for i in range(start, limit):
        line = lines[i]
        # Rough count — ignores strings/comments but good enough for structure
        opens = line.count("{") - line.count("\\{")
        closes = line.count("}") - line.count("\\}")
        depth += opens - closes
        if opens > 0:
            found_open = True
        if found_open and depth <= 0:
            return i
    return min(start + 100, len(lines) - 1)


def _find_block_end_py(lines: list[str], start: int) -> int:
    """Find end of Python def/class block by indentation tracking."""
    if start + 1 >= len(lines):
        return start
    # Find base indent of the def/class line
    base_indent = len(lines[start]) - len(lines[start].lstrip())
    last_content = start
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue  # blank lines don't end blocks
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent and re.match(r"\s*(?:async\s+)?def\s+|class\s+|@", line):
            return last_content
        last_content = i
    return last_content


# ── TS/JS symbol extraction ───────────────────────────────────────────────────

def _classify_ts(name: str, exported: bool) -> tuple[str, str]:
    """Returns (symbol_type, confidence)."""
    if re.match(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)$", name):
        return "api_route", "high"
    if name.startswith("use") and len(name) > 3 and name[3].isupper():
        return "hook", "high"
    if exported and name[0].isupper():
        return "use_case", "medium"   # could be component or class
    if exported:
        return "use_case", "high"
    return "utility", "medium"


def extract_symbols_ts(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, confidence: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = _find_block_end_ts(lines, line_no)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": confidence,
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    def line_of(match_start: int) -> int:
        return text[:match_start].count("\n")

    # Next.js route handlers: export async function GET(
    for m in re.finditer(
        r"^export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s*[\(<]",
        text, re.MULTILINE,
    ):
        add_sym(m.group(1), line_of(m.start()), "api_route", "high", True)

    # Named function exports: export [async] function name(
    for m in re.finditer(
        r"^(export\s+)?(default\s+)?(async\s+)?function\s+([A-Za-z_]\w*)\s*[\(<]",
        text, re.MULTILINE,
    ):
        name = m.group(4)
        exported = bool(m.group(1))
        sym_type, conf = _classify_ts(name, exported)
        if sym_type != "api_route":  # already captured above
            add_sym(name, line_of(m.start()), sym_type, conf, exported)

    # Arrow / const exports: export const name = (async)? (...) =>
    for m in re.finditer(
        r"^export\s+(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>|\w+\s*=>)",
        text, re.MULTILINE,
    ):
        name = m.group(1)
        sym_type, conf = _classify_ts(name, True)
        add_sym(name, line_of(m.start()), sym_type, conf, True)

    # Interfaces & types (models): export interface Foo / export type Foo =
    for m in re.finditer(
        r"^(export\s+)?(?:interface|type)\s+([A-Za-z_]\w*)\s*[={<]",
        text, re.MULTILINE,
    ):
        name = m.group(2)
        exported = bool(m.group(1))
        add_sym(name, line_of(m.start()), "model", "high", exported)

    # Classes: export class Foo
    for m in re.finditer(
        r"^(export\s+)?(?:default\s+)?class\s+([A-Za-z_]\w*)",
        text, re.MULTILINE,
    ):
        name = m.group(2)
        exported = bool(m.group(1))
        add_sym(name, line_of(m.start()), "model", "high", exported)

    # Zod schemas: const FooSchema = z.
    for m in re.finditer(
        r"^(?:export\s+)?const\s+([A-Za-z_]\w*[Ss]chema)\s*=\s*z\.",
        text, re.MULTILINE,
    ):
        name = m.group(1)
        add_sym(name, line_of(m.start()), "model", "high", True)

    return symbols


# ── Python symbol extraction ──────────────────────────────────────────────────

def extract_symbols_py(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    # Find route-decorated lines for fast lookup
    route_deco_lines: set[int] = set()
    for m in re.finditer(
        r"@(?:app|router|blueprint)\.(?:get|post|put|delete|patch)\s*\(",
        text, re.MULTILINE | re.IGNORECASE,
    ):
        route_deco_lines.add(text[:m.start()].count("\n"))

    def add_sym(name: str, line_no: int, sym_type: str, confidence: str) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = _find_block_end_py(lines, line_no)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": confidence,
            "exported": not name.startswith("_"),
            "keywords": _name_keywords(name),
        })

    # Functions: def / async def
    for m in re.finditer(
        r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
        text, re.MULTILINE,
    ):
        name = m.group(1)
        if name.startswith("_") or name.startswith("test_"):
            continue
        line_no = text[:m.start()].count("\n")
        # Check if decorated as a route (within 3 lines above)
        is_route = any(abs(line_no - dl) <= 3 for dl in route_deco_lines)
        sym_type = "api_route" if is_route else "use_case"
        add_sym(name, line_no, sym_type, "high")

    # Classes
    for m in re.finditer(r"^class\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        name = m.group(1)
        line_no = text[:m.start()].count("\n")
        add_sym(name, line_no, "model", "high")

    return symbols


# ── Keyword extraction (unchanged from original) ──────────────────────────────

def extract_keywords(content: str, ext: str) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        w = word.lower().strip("_")
        if len(w) >= 3 and w not in seen:
            seen.add(w); tokens.append(w)

    def add_name(name: str) -> None:
        add(name)
        for part in _split_camel(name):
            add(part)

    route_pat = re.compile(
        r"""(?:app|router|r|mux|api)\s*[.\@]\s*(get|post|put|delete|patch|handle|handlefunc)\s*\(\s*['"/]([^'")\s]+)""",
        re.IGNORECASE,
    )
    for m in route_pat.finditer(content):
        add(m.group(1).upper())
        for seg in m.group(2).strip("/").split("/"):
            seg = re.sub(r"[{}:<>]", "", seg)
            if seg: add(seg)

    dec_route = re.compile(r'@\w+\.(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
    for m in dec_route.finditer(content):
        add(m.group(1).upper())
        for seg in m.group(2).strip("/").split("/"):
            seg = re.sub(r"[{}:<>]", "", seg)
            if seg: add(seg)

    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        for m in re.finditer(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|type|interface|enum)\s+([A-Za-z_]\w*)", content):
            add_name(m.group(1))
        for m in re.finditer(r"export\s*\{([^}]+)\}", content):
            for name in re.split(r"[,\s]+", m.group(1)):
                name = name.strip()
                if name: add_name(name)

    if ext == ".py":
        for m in re.finditer(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m.group(1) or m.group(2)
            if name and not name.startswith("_"):
                add_name(name)
                for part in name.split("_"): add(part)

    if ext == ".go":
        for m in re.finditer(r"^func\s+(?:\([^)]+\)\s+)?([A-Z]\w*)", content, re.MULTILINE):
            add_name(m.group(1))

    if ext == ".swift":
        for m in re.finditer(r"^(?:public\s+|private\s+|internal\s+|open\s+|final\s+)*(?:class|struct|enum|protocol|actor|extension)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))
        for m in re.finditer(r"^(?:\s*)(?:public\s+|private\s+|internal\s+|open\s+|static\s+|class\s+|mutating\s+|override\s+)*func\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))

    doc_m = re.match(r'\s*"""([^"]{10,200})', content)
    if doc_m:
        for word in re.findall(r"[a-zA-Z]{4,}", doc_m.group(1)): add(word)
    jsdoc_m = re.match(r"\s*/\*\*?\s*([^\n*]{10,200})", content)
    if jsdoc_m:
        for word in re.findall(r"[a-zA-Z]{4,}", jsdoc_m.group(1)): add(word)

    http_call = re.compile(
        r"""(?:fetch|axios\.(?:get|post|put|delete)|requests\.(?:get|post|put|delete))\s*\(\s*[`'"](https?://[^`'"]+|/[^`'"]+)[`'"]""",
        re.IGNORECASE,
    )
    for m in http_call.finditer(content):
        url = m.group(1)
        for seg in url.replace("http://", "").replace("https://", "").strip("/").split("/"):
            seg = re.sub(r"[{}?=&<>]", "", seg).split(".")[0]
            if len(seg) >= 3: add(seg)

    return tokens[:80]


# ── File scanning ─────────────────────────────────────────────────────────────

def should_scan(path: Path) -> bool:
    posix = path.as_posix()
    if "/venv/" in posix or "/.venv/" in posix:
        return False
    return path.suffix.lower() in {
        ".go", ".py", ".js", ".jsx", ".ts", ".tsx", ".swift",
        ".json", ".yaml", ".yml", ".md",
    }


def walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        base = Path(dirpath)
        for name in filenames:
            path = base / name
            if should_scan(path) and path.is_file():
                files.append(path)
    return files


def parse_relations(path: Path, text: str, root: Path) -> list[dict]:
    edges: list[dict] = []
    file_id = rel(path, root)

    for match in re.finditer(r'import\s+\(?\s*"([^"]+)"', text):
        edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', text):
        edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'require\([\'"]([^\'"]+)[\'"]\)', text):
        edges.append({"from": file_id, "to": match.group(1), "rel": "requires"})
    for match in re.finditer(r'^\s*import\s+([a-zA-Z0-9_\.]+)', text, flags=re.MULTILINE):
        edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+', text, flags=re.MULTILINE):
        edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    if path.suffix == ".swift":
        for match in re.finditer(r'^import\s+([A-Za-z_]\w*)', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'([A-Za-z0-9_\-\/]+\.(go|py|ts|tsx|js|jsx|swift|md|json|yaml|yml))', text):
        candidate = match.group(1)
        if "/" in candidate:
            edges.append({"from": file_id, "to": candidate, "rel": "references"})

    return edges


def rel(path: Path, root: Path) -> str:
    return str(path.resolve().relative_to(root.resolve()))


def scan(root: Path) -> dict:
    nodes: list[Node] = []
    edges: list[dict] = []
    files = walk_files(root)

    for path in files:
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                continue
            content = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue

        file_id = rel(path, root)
        ext = path.suffix.lower()

        # File node (unchanged — keeps backward compat)
        file_node = Node(
            id=file_id,
            kind="file",
            path=file_id,
            ext=ext,
            size=size,
            keywords=extract_keywords(content, ext),
            content=content[:MAX_CONTENT_CHARS],
        )
        nodes.append(file_node)
        edges.extend(parse_relations(path, content, root))

        # Symbol nodes (Phase 1 addition)
        if ext in SYMBOL_EXTS:
            if ext in {".ts", ".tsx", ".js", ".jsx"}:
                syms = extract_symbols_ts(content, file_id)
            elif ext == ".py":
                syms = extract_symbols_py(content, file_id)
            else:
                syms = []

            for s in syms:
                sym_node = Node(
                    id=s["id"],
                    kind="symbol",
                    path=file_id,          # containing file
                    ext=ext,
                    size=s["line_end"] - s["line_start"] + 1,
                    keywords=s["keywords"],
                    symbol_type=s["symbol_type"],
                    name=s["name"],
                    line_start=s["line_start"],
                    line_end=s["line_end"],
                    body_hash=s["body_hash"],
                    confidence=s["confidence"],
                    exported=s["exported"],
                )
                nodes.append(sym_node)
                # file → contains → symbol
                edges.append({"from": file_id, "to": s["id"], "rel": "contains"})

    unique_edges = dedupe_edges(edges)
    symbol_count = sum(1 for n in nodes if n.kind == "symbol")
    return {
        "root": str(root),
        "node_count": len(nodes),
        "edge_count": len(unique_edges),
        "file_count": len(nodes) - symbol_count,
        "symbol_count": symbol_count,
        "nodes": [n.as_dict() for n in nodes],
        "edges": unique_edges,
    }


def dedupe_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge["rel"])
        if key not in seen:
            seen.add(key)
            out.append(edge)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan project and build information graph JSON.")
    parser.add_argument("--root", default=".", help="Project root to scan.")
    parser.add_argument("--out", default="dual-graph-dashboard/data/info_graph.json", help="Output JSON path.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    graph = scan(root)
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Scanned: {graph['file_count']} files, {graph['symbol_count']} symbols, {graph['edge_count']} edges")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
