#!/usr/bin/env python3
"""Build a lightweight information graph by scanning project files."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


SKIP_DIRS = {
    ".git",
    ".beads",
    ".beads-hooks",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".next",
    ".idea",
    ".vscode",
    "__pycache__",
    "venv",
    ".venv",
}

MAX_FILE_BYTES = 300_000
# Max chars of file content stored per node so graph_read works in remote
# (Railway) mode where the server cannot access the local filesystem.
MAX_CONTENT_CHARS = 24_000


@dataclass
class Node:
    id: str
    kind: str
    path: str
    ext: str
    size: int
    keywords: list[str]
    content: str = ""

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "ext": self.ext,
            "size": self.size,
            "keywords": self.keywords,
            "content": self.content,
        }


def _split_camel(name: str) -> list[str]:
    """Split camelCase/PascalCase into lowercase tokens: processPayment → [process, payment]."""
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    parts = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", parts)
    return [p.lower() for p in parts.split() if len(p) >= 3]


def extract_keywords(content: str, ext: str) -> list[str]:
    """
    Extract semantic keywords from file content without reading every line at query time.
    Returns lowercase tokens that describe what the file *does*, not what it *is named*.
    Handles: exported names, route paths, HTTP verbs, class names, docstring first lines.
    """
    tokens: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        w = word.lower().strip("_")
        if len(w) >= 3 and w not in seen:
            seen.add(w)
            tokens.append(w)

    def add_name(name: str) -> None:
        # Add the whole name and each camelCase segment.
        add(name)
        for part in _split_camel(name):
            add(part)

    # ── Route definitions (framework-agnostic) ────────────────────────────────
    # Express/Next: app.get('/path'), router.post('/path')
    # FastAPI/Flask: @app.get('/path'), @router.post('/path')
    # Go gin/chi/mux: r.GET("/path"), r.HandleFunc("/path")
    route_pat = re.compile(
        r"""(?:app|router|r|mux|api)\s*[.\@]\s*(get|post|put|delete|patch|handle|handlefunc)\s*\(\s*['"/]([^'")\s]+)""",
        re.IGNORECASE,
    )
    for m in route_pat.finditer(content):
        add(m.group(1).upper())  # HTTP verb as token: GET, POST, …
        for seg in m.group(2).strip("/").split("/"):
            seg = re.sub(r"[{}:<>]", "", seg)  # strip {param} markers
            if seg:
                add(seg)

    # Python decorator routes: @app.get("/path"), @router.delete("/orders/{id}")
    dec_route = re.compile(r'@\w+\.(get|post|put|delete|patch)\s*\(\s*[\'"]([^\'"]+)[\'"]', re.IGNORECASE)
    for m in dec_route.finditer(content):
        add(m.group(1).upper())
        for seg in m.group(2).strip("/").split("/"):
            seg = re.sub(r"[{}:<>]", "", seg)
            if seg:
                add(seg)

    # ── Exported / public symbols ─────────────────────────────────────────────
    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        # export function/const/class/type/interface FooBar
        for m in re.finditer(r"export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|type|interface|enum)\s+([A-Za-z_]\w*)", content):
            add_name(m.group(1))
        # export { foo, barBaz }
        for m in re.finditer(r"export\s*\{([^}]+)\}", content):
            for name in re.split(r"[,\s]+", m.group(1)):
                name = name.strip()
                if name:
                    add_name(name)

    if ext == ".py":
        # def foo_bar / async def / class FooBar
        for m in re.finditer(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m.group(1) or m.group(2)
            if name and not name.startswith("_"):
                add_name(name)
                # Also split snake_case: process_payment → [process, payment]
                for part in name.split("_"):
                    add(part)

    if ext == ".go":
        # func FooBar / func (r *Receiver) FooBar
        for m in re.finditer(r"^func\s+(?:\([^)]+\)\s+)?([A-Z]\w*)", content, re.MULTILINE):
            add_name(m.group(1))

    if ext == ".swift":
        # class/struct/enum/protocol/actor FooBar
        for m in re.finditer(r"^(?:public\s+|private\s+|internal\s+|open\s+|final\s+)*(?:class|struct|enum|protocol|actor|extension)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))
        # func fooBar / mutating func / static func
        for m in re.finditer(r"^(?:\s*)(?:public\s+|private\s+|internal\s+|open\s+|static\s+|class\s+|mutating\s+|override\s+)*func\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))
        # var/let declarations at top level: var paymentStatus
        for m in re.finditer(r"^\s*(?:@\w+\s+)*(?:public\s+|private\s+|internal\s+)?(?:var|let)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))

    # ── Docstring / file-level comment (first meaningful line) ────────────────
    # Python: """...""" at file top
    doc_m = re.match(r'\s*"""([^"]{10,200})', content)
    if doc_m:
        for word in re.findall(r"[a-zA-Z]{4,}", doc_m.group(1)):
            add(word)
    # JS/TS: /** ... */ or // filename description
    jsdoc_m = re.match(r"\s*/\*\*?\s*([^\n*]{10,200})", content)
    if jsdoc_m:
        for word in re.findall(r"[a-zA-Z]{4,}", jsdoc_m.group(1)):
            add(word)

    # ── HTTP client calls: fetch/axios/requests (cross-service signal) ────────
    http_call = re.compile(
        r"""(?:fetch|axios\.(?:get|post|put|delete)|requests\.(?:get|post|put|delete))\s*\(\s*[`'"](https?://[^`'"]+|/[^`'"]+)[`'"]""",
        re.IGNORECASE,
    )
    for m in http_call.finditer(content):
        url = m.group(1)
        for seg in url.replace("http://", "").replace("https://", "").strip("/").split("/"):
            seg = re.sub(r"[{}?=&<>]", "", seg).split(".")[0]
            if len(seg) >= 3:
                add(seg)

    return tokens[:80]  # cap to keep node size bounded


def should_scan(path: Path) -> bool:
    posix = path.as_posix()
    if "/venv/" in posix or "/.venv/" in posix:
        return False
    return path.suffix.lower() in {
        ".go",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".swift",
        ".json",
        ".yaml",
        ".yml",
        ".md",
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

    # Go imports.
    for match in re.finditer(r'import\s+\(?\s*"([^"]+)"', text):
        edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'"([^"]+)"', text):
        if path.suffix == ".go" and "/" in match.group(1):
            edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})

    # JS/TS imports.
    for match in re.finditer(r'import\s+.*?\s+from\s+[\'"]([^\'"]+)[\'"]', text):
        edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'require\([\'"]([^\'"]+)[\'"]\)', text):
        edges.append({"from": rel(path, root), "to": match.group(1), "rel": "requires"})

    # Python imports.
    for match in re.finditer(r'^\s*import\s+([a-zA-Z0-9_\.]+)', text, flags=re.MULTILINE):
        edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})
    for match in re.finditer(r'^\s*from\s+([a-zA-Z0-9_\.]+)\s+import\s+', text, flags=re.MULTILINE):
        edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})

    # Swift imports.
    if path.suffix == ".swift":
        for match in re.finditer(r'^import\s+([A-Za-z_]\w*)', text, flags=re.MULTILINE):
            edges.append({"from": rel(path, root), "to": match.group(1), "rel": "imports"})

    # Rough in-repo path references.
    for match in re.finditer(r'([A-Za-z0-9_\-\/]+\.(go|py|ts|tsx|js|jsx|swift|md|json|yaml|yml))', text):
        candidate = match.group(1)
        if "/" in candidate:
            edges.append({"from": rel(path, root), "to": candidate, "rel": "references"})

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

        node = Node(
            id=rel(path, root),
            kind="file",
            path=rel(path, root),
            ext=path.suffix.lower(),
            size=size,
            keywords=extract_keywords(content, path.suffix.lower()),
            content=content[:MAX_CONTENT_CHARS],
        )
        nodes.append(node)
        edges.extend(parse_relations(path, content, root))

    unique_edges = dedupe_edges(edges)
    return {
        "root": str(root),
        "node_count": len(nodes),
        "edge_count": len(unique_edges),
        "nodes": [n.as_dict() for n in nodes],
        "edges": unique_edges,
    }


def dedupe_edges(edges: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for edge in edges:
        key = (edge["from"], edge["to"], edge["rel"])
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan project and build information graph JSON.")
    parser.add_argument("--root", default=".", help="Project root to scan.")
    parser.add_argument(
        "--out",
        default="dual-graph-dashboard/data/info_graph.json",
        help="Output JSON path.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    graph = scan(root)
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"Scanned: {graph['node_count']} nodes, {graph['edge_count']} edges")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
