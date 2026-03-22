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
SYMBOL_EXTS = {".ts", ".tsx", ".js", ".jsx", ".py", ".rs", ".java", ".cs", ".rb", ".php", ".kt", ".c", ".cpp", ".h", ".hpp"}


@dataclass
class Node:
    id: str
    kind: str       # "file" or "symbol"
    path: str       # relative file path (for symbols: the containing file)
    ext: str
    size: int
    keywords: list[str]
    content: str = ""
    summary: str = ""       # heuristic NL summary (file nodes only)
    file_hash: str = ""     # md5[:8] of file content for incremental rescan
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
            d["summary"] = self.summary
            d["file_hash"] = self.file_hash
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

    # Directly match route decorator immediately before a function def
    # (only decorator lines and blank lines may appear between decorator and def)
    route_names: set[str] = set()
    for m in re.finditer(
        r"@(?:app|router|blueprint)\.(?:get|post|put|delete|patch)\s*\([^)]*\)"
        r"(?:\n[ \t]*@[^\n]*)?"  # allow one extra decorator line
        r"\n[ \t]*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(",
        text, re.MULTILINE | re.IGNORECASE,
    ):
        route_names.add(m.group(1))

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
        sym_type = "api_route" if name in route_names else "use_case"
        add_sym(name, line_no, sym_type, "high")

    # Classes
    for m in re.finditer(r"^class\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        name = m.group(1)
        line_no = text[:m.start()].count("\n")
        add_sym(name, line_no, "model", "high")

    return symbols


# ── Rust symbol extraction ────────────────────────────────────────────────────

def extract_symbols_rs(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = min(line_no + 50, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    # Only extract pub fns — private helpers add noise without value
    for m in re.finditer(r"^pub(?:\s*\([^)]*\))?\s+(?:async\s+)?fn\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        add_sym(m.group(1), text[:m.start()].count("\n"), "use_case", True)
    for m in re.finditer(r"^(?P<pub>pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        add_sym(m.group(2), text[:m.start()].count("\n"), "model", bool(m.group("pub")))
    return symbols


# ── Java / Kotlin symbol extraction ──────────────────────────────────────────

def extract_symbols_java(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = min(line_no + 60, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    for m in re.finditer(r"(?:public|private|protected|\s)+(?:class|interface|enum|record|object|data\s+class|sealed\s+class|abstract\s+class)\s+([A-Za-z_]\w*)", text):
        exported = "public" in text[m.start():m.start() + 20]
        add_sym(m.group(1), text[:m.start()].count("\n"), "model", exported)
    # Methods: access modifier + return type + name(
    for m in re.finditer(r"(?:public|private|protected)\s+(?:static\s+)?(?:final\s+)?(?!class|if|for|while|return|new)\w[\w<>\[\]]*\s+([A-Za-z_]\w*)\s*\(", text):
        name = m.group(1)
        if name[0].islower():  # skip constructor-style (PascalCase already caught above)
            exported = "public" in text[m.start():m.start() + 30]
            add_sym(name, text[:m.start()].count("\n"), "use_case", exported)
    return symbols


# ── C# symbol extraction ──────────────────────────────────────────────────────

def extract_symbols_cs(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = min(line_no + 60, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    for m in re.finditer(r"(?:public|internal|private|protected|\s)+(?:class|interface|enum|struct|record)\s+([A-Za-z_]\w*)", text):
        exported = "public" in text[m.start():m.start() + 20]
        add_sym(m.group(1), text[:m.start()].count("\n"), "model", exported)
    for m in re.finditer(r"(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?(?:virtual\s+|override\s+)?(?!class\b|if\b|for\b|while\b|return\b|new\b)[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\(", text):
        name = m.group(1)
        if name not in ("if", "for", "while", "return", "new", "class"):
            exported = "public" in text[m.start():m.start() + 30]
            add_sym(name, text[:m.start()].count("\n"), "use_case", exported)
    return symbols


# ── Ruby symbol extraction ────────────────────────────────────────────────────

def extract_symbols_rb(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str) -> None:
        if name in seen or not name or name.startswith("_"):
            return
        seen.add(name)
        end = min(line_no + 40, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": True,
            "keywords": _name_keywords(name),
        })

    for m in re.finditer(r"^\s*def\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        add_sym(m.group(1), text[:m.start()].count("\n"), "use_case")
    for m in re.finditer(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        add_sym(m.group(1), text[:m.start()].count("\n"), "model")
    return symbols


# ── PHP symbol extraction ─────────────────────────────────────────────────────

def extract_symbols_php(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = min(line_no + 50, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    for m in re.finditer(r"(?:public|private|protected|\s)(?:static\s+)?function\s+([A-Za-z_]\w*)", text):
        exported = "public" in text[m.start():m.start() + 20]
        add_sym(m.group(1), text[:m.start()].count("\n"), "use_case", exported)
    for m in re.finditer(r"(?:class|interface|trait)\s+([A-Za-z_]\w*)", text):
        add_sym(m.group(1), text[:m.start()].count("\n"), "model", True)
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

    if ext == ".rs":
        for m in re.finditer(r"^(?:pub(?:\s*\([^)]*\))?\s+)?fn\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))
        for m in re.finditer(r"^(?:pub\s+)?(?:struct|enum|trait|impl(?:\s+\w+\s+for)?)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            add_name(m.group(1))

    if ext in {".java", ".kt"}:
        for m in re.finditer(r"(?:public|private|protected|static|final|\s)+(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", content):
            add_name(m.group(1))
        for m in re.finditer(r"(?:public|private|protected|static|final|\s)+(?!class|if|for|while|return)\w[\w<>\[\]]*\s+([A-Za-z_]\w*)\s*\(", content):
            add_name(m.group(1))
        if ext == ".kt":
            for m in re.finditer(r"^(?:(?:public|private|internal|protected|open|data|sealed|abstract)\s+)*(?:class|object|interface|fun)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
                add_name(m.group(1))

    if ext == ".cs":
        for m in re.finditer(r"(?:public|private|protected|internal|static|sealed|abstract|\s)+(?:class|interface|enum|struct|record)\s+([A-Za-z_]\w*)", content):
            add_name(m.group(1))
        for m in re.finditer(r"(?:public|private|protected|internal|static|virtual|override|async|\s)+(?!class|if|for|while|return)[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\(", content):
            add_name(m.group(1))

    if ext == ".rb":
        for m in re.finditer(r"^\s*(?:def\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|module\s+([A-Za-z_]\w*))", content, re.MULTILINE):
            add_name(m.group(1) or m.group(2) or m.group(3))

    if ext == ".php":
        for m in re.finditer(r"(?:function\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|interface\s+([A-Za-z_]\w*)|trait\s+([A-Za-z_]\w*))", content):
            add_name(m.group(1) or m.group(2) or m.group(3) or m.group(4))

    if ext in {".c", ".cpp", ".h", ".hpp"}:
        # Functions: return_type function_name(
        for m in re.finditer(r"^[\w:*&<>\s]+?\s+([A-Za-z_]\w*)\s*\([^;]*$", content, re.MULTILINE):
            name = m.group(1)
            if name not in {"if", "for", "while", "switch", "return", "sizeof", "catch"}:
                add_name(name)
        # Classes, structs, enums, namespaces
        for m in re.finditer(r"^(?:class|struct|enum|namespace|union)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
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


# ── NL summary generation (heuristic, no LLM) ────────────────────────────────

def _make_summary(content: str, path: str, ext: str) -> str:
    """
    Generate a 1-2 sentence NL summary from file content using heuristics only.
    Template: "Handles <domain>. Contains <N> functions/classes: <names>."
    """
    lines = content.splitlines()

    # 1. Extract leading docstring / block comment (first 200 chars max)
    lead = ""
    if ext == ".py":
        m = re.search(r'^\s*(?:\'\'\'|""")([^\'\"]{8,200}?)(?:\'\'\'|""")', content, re.DOTALL)
        if m:
            lead = " ".join(m.group(1).split())[:120]
    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        m = re.match(r"\s*/\*\*?\s*(.*?)\*/", content, re.DOTALL)
        if m:
            lead = " ".join(m.group(1).replace("*", "").split())[:120]
    if not lead:
        # Try first non-empty line comment
        for line in lines[:5]:
            s = line.strip().lstrip("#").lstrip("//").strip()
            if len(s) >= 10:
                lead = s[:120]
                break

    # 2. Collect function/class names (max 5)
    names: list[str] = []
    if ext == ".py":
        for m2 in re.finditer(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)|^class\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m2.group(1) or m2.group(2)
            if name and not name.startswith("_") and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext in {".ts", ".tsx", ".js", ".jsx"}:
        for m2 in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_]\w*)|(?:export\s+)?class\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m2.group(1) or m2.group(2)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext == ".rs":
        for m2 in re.finditer(r"^(?:pub(?:\s*\([^)]*\))?\s+)?fn\s+([A-Za-z_]\w*)|^(?:pub\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m2.group(1) or m2.group(2)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext in {".java", ".kt"}:
        for m2 in re.finditer(r"(?:class|interface|enum|fun|record)\s+([A-Za-z_]\w*)", content):
            name = m2.group(1)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext == ".cs":
        for m2 in re.finditer(r"(?:class|interface|enum|struct|record)\s+([A-Za-z_]\w*)", content):
            name = m2.group(1)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext == ".rb":
        for m2 in re.finditer(r"^\s*(?:def\s+([A-Za-z_]\w*)|class\s+([A-Za-z_]\w*)|module\s+([A-Za-z_]\w*))", content, re.MULTILINE):
            name = m2.group(1) or m2.group(2) or m2.group(3)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext == ".php":
        for m2 in re.finditer(r"(?:function|class|interface|trait)\s+([A-Za-z_]\w*)", content):
            name = m2.group(1)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
    elif ext in {".c", ".cpp", ".h", ".hpp"}:
        for m2 in re.finditer(r"^(?:class|struct|enum|union|namespace)\s+([A-Za-z_]\w*)", content, re.MULTILINE):
            name = m2.group(1)
            if name and name not in names:
                names.append(name)
                if len(names) >= 5:
                    break
        if len(names) < 5:
            for m2 in re.finditer(r"^[\w:*&<>\s]+?\s+([A-Za-z_]\w*)\s*\([^;{]*\{", content, re.MULTILINE):
                name = m2.group(1)
                if name and name not in {"if", "for", "while", "switch", "return", "sizeof", "catch"} and name not in names:
                    names.append(name)
                    if len(names) >= 5:
                        break

    # 3. Infer domain from path segments
    parts = [p for p in re.split(r"[/\\]", path) if p and p != "."]
    # Skip generic top-level dirs
    domain_parts = [p for p in parts if p.lower() not in {"src", "lib", "app", "pkg", "main", "index"}]
    domain = " ".join(domain_parts[-2:]).replace("_", " ").replace("-", " ") if domain_parts else parts[-1] if parts else ""
    # Remove file extension from domain
    domain = re.sub(r"\.\w+$", "", domain).strip()

    # 4. Assemble summary
    parts_out: list[str] = []
    if lead:
        sentence = lead.rstrip(".") + "."
        parts_out.append(sentence)
    elif domain:
        parts_out.append(f"Handles {domain}.")

    if names:
        n_label = "functions/classes" if len(names) > 1 else "function"
        names_str = ", ".join(names[:4])
        if len(names) >= 5:
            names_str += ", ..."
        parts_out.append(f"Contains {len(names)} {n_label}: {names_str}.")

    return " ".join(parts_out)[:250]


# ── File scanning ─────────────────────────────────────────────────────────────

def should_scan(path: Path) -> bool:
    posix = path.as_posix()
    if "/venv/" in posix or "/.venv/" in posix:
        return False
    return path.suffix.lower() in {
        ".go", ".py", ".js", ".jsx", ".ts", ".tsx", ".swift",
        ".rs", ".java", ".cs", ".rb", ".php", ".kt",
        ".c", ".cpp", ".h", ".hpp",
        ".json", ".yaml", ".yml", ".md",
    }


def walk_files(root: Path) -> list[Path]:
    files: list[Path] = []
    root_resolved = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        base = Path(dirpath)
        # Prune: skip blacklisted dirs and symlinked dirs that escape the root.
        def _keep_dir(d: str) -> bool:
            if d in SKIP_DIRS:
                return False
            p = (base / d)
            try:
                if p.is_symlink():
                    if not p.resolve().is_relative_to(root_resolved):
                        return False
            except Exception:
                return False
            return True
        dirnames[:] = [d for d in dirnames if _keep_dir(d)]
        for name in filenames:
            path = base / name
            try:
                if should_scan(path) and path.is_file():
                    files.append(path)
            except (PermissionError, OSError):
                pass
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
    if path.suffix == ".rs":
        for match in re.finditer(r'^use\s+([\w:]+)', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
        for match in re.finditer(r'^mod\s+([A-Za-z_]\w*)', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    if path.suffix in {".java", ".kt"}:
        for match in re.finditer(r'^import\s+([\w.]+)', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    if path.suffix == ".cs":
        for match in re.finditer(r'^using\s+([\w.]+)', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    if path.suffix == ".rb":
        for match in re.finditer(r"(?:require|require_relative)\s+['\"]([^'\"]+)['\"]", text):
            edges.append({"from": file_id, "to": match.group(1), "rel": "requires"})
    if path.suffix == ".php":
        for match in re.finditer(r"^use\s+([\w\\]+)", text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "imports"})
    if path.suffix in {".c", ".cpp", ".h", ".hpp"}:
        for match in re.finditer(r'^#include\s+"([^"]+)"', text, flags=re.MULTILINE):
            edges.append({"from": file_id, "to": match.group(1), "rel": "includes"})
    for match in re.finditer(r'([A-Za-z0-9_\-\/]+\.(go|py|ts|tsx|js|jsx|swift|rs|java|cs|rb|php|kt|c|cpp|h|hpp|md|json|yaml|yml))', text):
        candidate = match.group(1)
        if "/" in candidate:
            edges.append({"from": file_id, "to": candidate, "rel": "references"})

    return edges


def rel(path: Path, root: Path) -> str:
    """Return a stable relative ID for *path* w.r.t. *root*.

    Uses ``relative_to`` when the resolved path is inside the root (normal
    case).  Falls back to ``os.path.relpath`` for symlinks or virtual links
    that resolve to a location *outside* the root, which would otherwise raise
    ``ValueError`` and crash the scan.
    """
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        # Path resolves outside root (e.g. a cross-project symlink).
        # Use relpath so the ID is still meaningful and collision-free.
        return os.path.relpath(path.resolve(), root.resolve())


def extract_symbols_c_cpp(content: str, file_path: str) -> list[dict]:
    lines = content.splitlines()
    text = content
    symbols: list[dict] = []
    seen: set[str] = set()

    def add_sym(name: str, line_no: int, sym_type: str, exported: bool) -> None:
        if name in seen or not name:
            return
        seen.add(name)
        end = min(line_no + 50, len(lines) - 1)
        symbols.append({
            "id": f"{file_path}::{name}",
            "name": name,
            "symbol_type": sym_type,
            "line_start": line_no,
            "line_end": end,
            "body_hash": _body_hash(lines, line_no, end),
            "confidence": "high",
            "exported": exported,
            "keywords": _name_keywords(name),
        })

    SKIP = {"if", "for", "while", "switch", "return", "sizeof", "catch", "else", "do"}
    # Classes, structs, enums, unions, namespaces
    for m in re.finditer(r"^(?:class|struct|enum|union|namespace)\s+([A-Za-z_]\w*)", text, re.MULTILINE):
        sym_type = "model" if m.group(0).startswith(("class", "struct", "union", "enum")) else "namespace"
        add_sym(m.group(1), text[:m.start()].count("\n"), sym_type, True)
    # Functions: return_type name( — must not end with ; (declaration vs definition)
    for m in re.finditer(r"^[\w:*&<>\s]+?\s+([A-Za-z_]\w*)\s*\([^;{]*\{", text, re.MULTILINE):
        name = m.group(1)
        if name not in SKIP:
            add_sym(name, text[:m.start()].count("\n"), "use_case", True)
    return symbols


def _extract_symbols_for_file(content: str, file_id: str, ext: str) -> list[dict]:
    if ext in {".ts", ".tsx", ".js", ".jsx"}:
        return extract_symbols_ts(content, file_id)
    if ext == ".py":
        return extract_symbols_py(content, file_id)
    if ext == ".rs":
        return extract_symbols_rs(content, file_id)
    if ext in {".java", ".kt"}:
        return extract_symbols_java(content, file_id)
    if ext == ".cs":
        return extract_symbols_cs(content, file_id)
    if ext == ".rb":
        return extract_symbols_rb(content, file_id)
    if ext == ".php":
        return extract_symbols_php(content, file_id)
    if ext in {".c", ".cpp", ".h", ".hpp"}:
        return extract_symbols_c_cpp(content, file_id)
    return []


def _append_symbol_nodes(nodes: list[Node], edges: list[dict], syms: list[dict], file_id: str, ext: str) -> None:
    for s in syms:
        sym_node = Node(
            id=s["id"],
            kind="symbol",
            path=file_id,
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
        edges.append({"from": file_id, "to": s["id"], "rel": "contains"})


def scan(root: Path, existing_nodes: dict[str, dict] | None = None) -> dict:
    """Scan project files.

    Args:
        root: Project root directory.
        existing_nodes: Optional mapping of file_id → existing node dict for
            incremental re-scan.  Files whose content hash matches the stored
            ``file_hash`` are skipped (their existing node is reused as-is).
    """
    nodes: list[Node] = []
    edges: list[dict] = []
    files = walk_files(root)
    prior: dict[str, dict] = existing_nodes or {}

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
        fhash = hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()[:8]

        # Incremental: reuse existing node if content unchanged.
        if file_id in prior:
            old = prior[file_id]
            if old.get("file_hash") == fhash:
                # Reconstruct node from stored data (preserves summary + keywords).
                old_node = Node(
                    id=old["id"],
                    kind=old.get("kind", "file"),
                    path=old.get("path", file_id),
                    ext=old.get("ext", ext),
                    size=old.get("size", size),
                    keywords=old.get("keywords", []),
                    content=old.get("content", content[:MAX_CONTENT_CHARS]),
                    summary=old.get("summary", ""),
                    file_hash=fhash,
                )
                nodes.append(old_node)
                edges.extend(parse_relations(path, content, root))
                if ext in SYMBOL_EXTS:
                    _append_symbol_nodes(nodes, edges, _extract_symbols_for_file(content, file_id, ext), file_id, ext)
                continue  # Skip re-summarising unchanged file

        # Generate heuristic NL summary for this file.
        summary = _make_summary(content, file_id, ext)

        # File node
        file_node = Node(
            id=file_id,
            kind="file",
            path=file_id,
            ext=ext,
            size=size,
            keywords=extract_keywords(content, ext),
            content=content[:MAX_CONTENT_CHARS],
            summary=summary,
            file_hash=fhash,
        )
        nodes.append(file_node)
        edges.extend(parse_relations(path, content, root))

        # Symbol nodes (Phase 1 addition)
        if ext in SYMBOL_EXTS:
            _append_symbol_nodes(nodes, edges, _extract_symbols_for_file(content, file_id, ext), file_id, ext)

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

    # Load existing graph for incremental re-scan (reuse summaries for unchanged files).
    existing_nodes: dict = {}
    if out_path.exists():
        try:
            old_graph = json.loads(out_path.read_text(encoding="utf-8"))
            existing_nodes = {n["id"]: n for n in old_graph.get("nodes", []) if n.get("kind") == "file"}
        except Exception:
            pass

    graph = scan(root, existing_nodes=existing_nodes)
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")

    # Write flat symbol index alongside info_graph.json for O(1) graph_read lookups.
    sym_index = {
        node["id"]: {
            "line_start": node["line_start"],
            "line_end": node["line_end"],
            "body_hash": node["body_hash"],
            "confidence": node.get("confidence", ""),
            "path": node["path"],
        }
        for node in graph["nodes"]
        if node.get("kind") == "symbol"
    }
    sym_index_path = out_path.parent / "symbol_index.json"
    sym_index_path.write_text(json.dumps(sym_index), encoding="utf-8")

    print(f"Scanned: {graph['file_count']} files, {graph['symbol_count']} symbols, {graph['edge_count']} edges")
    print(f"Wrote: {out_path}")
    print(f"Symbol index: {sym_index_path} ({len(sym_index)} symbols)")


if __name__ == "__main__":
    main()
