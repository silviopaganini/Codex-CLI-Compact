#!/usr/bin/env bash
# Shared local launcher for dual-graph MCP workflows.
# Wrapper scripts:
#   dg  -> codex
#   dgc -> claude

set -euo pipefail

ASSISTANT="${1:-}"
if [[ "$ASSISTANT" != "codex" && "$ASSISTANT" != "claude" ]]; then
  echo "Usage: $0 <codex|claude> [project_path] [prompt]" >&2
  exit 2
fi
shift

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
PROJECT="${1:-$(pwd)}"
PROJECT="$(cd "$PROJECT" && pwd)"
PROMPT="${2:-}"
DATA_DIR="$PROJECT/.dual-graph"

# ── Kill any stale MCP server for this project (frees its port before scanning) ─
if [[ -f "$DATA_DIR/mcp_server.pid" ]]; then
  _OLD_PID="$(cat "$DATA_DIR/mcp_server.pid")"
  if kill -0 "$_OLD_PID" 2>/dev/null; then
    kill "$_OLD_PID" 2>/dev/null || true
    sleep 0.3
  fi
  rm -f "$DATA_DIR/mcp_server.pid"
fi
# ──────────────────────────────────────────────────────────────────────────────

# Find a free port starting at 8080 (or use DG_MCP_PORT if set)
if [[ -n "${DG_MCP_PORT:-}" ]]; then
  MCP_PORT="$DG_MCP_PORT"
else
  MCP_PORT=8080
  while lsof -ti :"$MCP_PORT" >/dev/null 2>&1; do
    MCP_PORT=$((MCP_PORT + 1))
    if [[ $MCP_PORT -gt 8099 ]]; then
      echo "[$TOOL_LABEL] Error: no free port found in range 8080-8099" >&2
      exit 1
    fi
  done
fi

if [[ "$ASSISTANT" == "codex" ]]; then
  TOOL_LABEL="dg"
  DOC_FILE="$PROJECT/CODEX.md"
  DOC_NAME="CODEX.md"
  POLICY_MARKER="dg-policy-v5"
  CONTEXT_DIR="$PROJECT/.dual-graph-context"
else
  TOOL_LABEL="dgc"
  DOC_FILE="$PROJECT/CLAUDE.md"
  DOC_NAME="CLAUDE.md"
  POLICY_MARKER="dgc-policy-v9"
fi

# ── Self-update ────────────────────────────────────────────────────────────────
_R2="https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
_LOCAL_VER="$(cat "$SCRIPT_DIR/version.txt" 2>/dev/null || echo "0")"
_REMOTE_VER="$(curl -sf --max-time 3 "$_R2/version.txt" 2>/dev/null || echo "")"

if [[ -n "$_REMOTE_VER" && "$_REMOTE_VER" != "$_LOCAL_VER" ]]; then
  echo "[$TOOL_LABEL] Update available ($_LOCAL_VER → $_REMOTE_VER) — updating..."
  curl -sSL "$_R2/mcp_graph_server.py"  -o "$SCRIPT_DIR/mcp_graph_server.py"
  curl -sSL "$_R2/graph_builder.py"     -o "$SCRIPT_DIR/graph_builder.py"
  curl -sSL "$_R2/dg.py"               -o "$SCRIPT_DIR/dg.py"
  curl -sSL "$_R2/dual_graph_launch.sh" -o "$SCRIPT_DIR/dual_graph_launch.sh" \
    && chmod +x "$SCRIPT_DIR/dual_graph_launch.sh"
  echo "$_REMOTE_VER" > "$SCRIPT_DIR/version.txt"
  echo "[$TOOL_LABEL] Updated to $_REMOTE_VER. Restarting..."
  EXEC_ARGS=("$SCRIPT_DIR/dual_graph_launch.sh" "$ASSISTANT" "$PROJECT")
  [[ -n "$PROMPT" ]] && EXEC_ARGS+=("$PROMPT")
  exec "${EXEC_ARGS[@]}"
fi
# ──────────────────────────────────────────────────────────────────────────────

if [[ ! -x "$VENV/bin/python3" ]]; then
  echo "[$TOOL_LABEL] Creating venv at $VENV ..."
  python3 -m venv "$VENV"
  echo "[$TOOL_LABEL] Installing Python dependencies..."
  "$VENV/bin/pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet
elif ! "$VENV/bin/python3" -c "import mcp, uvicorn, anyio, starlette" 2>/dev/null; then
  echo "[$TOOL_LABEL] Installing missing Python dependencies..."
  "$VENV/bin/pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet
fi

PYTHON="$VENV/bin/python3"

echo "[$TOOL_LABEL] Project : $PROJECT"
echo "[$TOOL_LABEL] Data    : $DATA_DIR"
echo ""

mkdir -p "$DATA_DIR"

if [[ -f "$PROJECT/.gitignore" ]] && ! grep -qx '.dual-graph/' "$PROJECT/.gitignore" 2>/dev/null; then
  echo '.dual-graph/' >> "$PROJECT/.gitignore"
  echo "[$TOOL_LABEL] Added .dual-graph/ to .gitignore"
fi

if [[ "$ASSISTANT" == "codex" ]] && [[ -f "$PROJECT/.gitignore" ]] && ! grep -qx '.dual-graph-context/' "$PROJECT/.gitignore" 2>/dev/null; then
  echo '.dual-graph-context/' >> "$PROJECT/.gitignore"
  echo "[$TOOL_LABEL] Added .dual-graph-context/ to .gitignore"
fi

_ensure_codex_context_files() {
  [[ "$ASSISTANT" == "codex" ]] || return 0

  mkdir -p "$CONTEXT_DIR/packs"

  if [[ ! -f "$CONTEXT_DIR/PROJECT_CONTEXT.md" ]]; then
    cat > "$CONTEXT_DIR/PROJECT_CONTEXT.md" << 'EOF'
# PROJECT_CONTEXT

## Product Goal
- What are we building and for whom?

## Architecture Snapshot
- Main services/apps:
- Key data flow:
- Critical dependencies:

## Non-Negotiable Constraints
- Security / compliance:
- Performance targets:
- Tech constraints:

## Definition Of Done
- Release criteria:
- Test/validation criteria:

## Out Of Scope
- Explicitly excluded changes:
EOF
  fi

  if [[ ! -f "$CONTEXT_DIR/SESSION_CONTEXT.md" ]]; then
    cat > "$CONTEXT_DIR/SESSION_CONTEXT.md" << 'EOF'
# SESSION_CONTEXT

## Current Objective
- What outcome should this session produce?

## Active Scope
- In-scope modules/files:
- Out-of-scope modules/files:

## Acceptance Criteria
- Concrete checks this task must pass:

## Decisions / Assumptions
- Decision:
- Why:

## Open Questions
- Missing details that block implementation:
EOF
  fi

  if [[ ! -f "$CONTEXT_DIR/packs/README.md" ]]; then
    cat > "$CONTEXT_DIR/packs/README.md" << 'EOF'
# Context Packs

Use one file per domain area. Examples:
- auth.md
- billing.md
- checkout.md
- notifications.md

Keep each pack short and factual:
- domain rules
- edge cases
- invariants
- API contracts
EOF
  fi
}

_write_codex_policy_doc() {
  cat > "$DOC_FILE" << EOF
<!-- $POLICY_MARKER -->
# Dual-Graph Context Policy

This project uses a local dual-graph MCP server for efficient context retrieval.

## Context Layering (Codex Only)

- Use layered context files:
  - \`.dual-graph-context/PROJECT_CONTEXT.md\` for stable project context.
  - \`.dual-graph-context/SESSION_CONTEXT.md\` for current in-chat scope.
  - \`.dual-graph-context/packs/*.md\` for domain-specific context packs.
- Never ask for "full context" or entire chat history.
- Ask only for missing sections, one short question at a time.
- If a domain is missing context, request only that pack (for example: "please share billing context pack").

## MANDATORY: Always follow this order

1. **Call \`graph_continue\` first** — before any file exploration, grep, or code reading.

2. **If \`graph_continue\` returns \`needs_project=true\`**: call \`graph_scan\` with the
   current project directory (\`pwd\`). Do NOT ask the user.

3. **If \`graph_continue\` returns \`skip=true\`**: project has fewer than 5 files.
   Do NOT do broad or recursive exploration. Read only specific files if their names
   are mentioned, or ask the user what to work on.

4. **Load context layers before implementation decisions**:
   - Read \`.dual-graph-context/PROJECT_CONTEXT.md\` and \`.dual-graph-context/SESSION_CONTEXT.md\` when available.
   - Read only relevant \`.dual-graph-context/packs/*.md\` files for the current task.
   - If critical context is missing, ask one scoped question and continue after answer.

5. **Read \`recommended_files\`** using \`graph_read\`.
   - \`recommended_files\` may contain \`file::symbol\` entries (e.g. \`src/auth.ts::handleLogin\`).
     Pass them verbatim to \`graph_read\` — it reads only that symbol's lines, not the full file.

6. **Check \`confidence\` and obey the caps strictly:**
   - \`confidence=high\` -> Stop. Do NOT grep or explore further.
   - \`confidence=medium\` -> If recommended files are insufficient, call \`fallback_rg\`
     at most \`max_supplementary_greps\` time(s) with specific terms, then \`graph_read\`
     at most \`max_supplementary_files\` additional file(s). Then stop.
   - \`confidence=low\` -> Call \`fallback_rg\` at most \`max_supplementary_greps\` time(s),
     then \`graph_read\` at most \`max_supplementary_files\` file(s). Then stop.

## Rules

- Do NOT use \`rg\`, \`grep\`, or bash file exploration before calling \`graph_continue\`.
- Do NOT do broad/recursive exploration at any confidence level.
- \`max_supplementary_greps\` and \`max_supplementary_files\` are hard caps - never exceed them.
- Do NOT dump full chat history.
- Do context handshake per task: summarize known context, then ask for only missing pieces.
- Do NOT call \`graph_retrieve\` more than once per turn.
- After edits, call \`graph_register_edit\` with the changed files. Use \`file::symbol\` notation (e.g. \`src/auth.ts::handleLogin\`) when the edit targets a specific function, class, or hook.
EOF
}

_write_claude_policy_doc() {
  cat > "$DOC_FILE" << EOF
<!-- $POLICY_MARKER -->
# Dual-Graph Context Policy

This project uses a local dual-graph MCP server for efficient context retrieval.

## MANDATORY: Always follow this order

1. **Call \`graph_continue\` first** — before any file exploration, grep, or code reading.

2. **If \`graph_continue\` returns \`needs_project=true\`**: call \`graph_scan\` with the
   current project directory (\`pwd\`). Do NOT ask the user.

3. **If \`graph_continue\` returns \`skip=true\`**: project has fewer than 5 files.
   Do NOT do broad or recursive exploration. Read only specific files if their names
   are mentioned, or ask the user what to work on.

4. **Read \`recommended_files\`** using \`graph_read\`.
   - \`recommended_files\` may contain \`file::symbol\` entries (e.g. \`src/auth.ts::handleLogin\`).
     Pass them verbatim to \`graph_read\` — it reads only that symbol's lines, not the full file.

5. **Check \`confidence\` and obey the caps strictly:**
   - \`confidence=high\` -> Stop. Do NOT grep or explore further.
   - \`confidence=medium\` -> If recommended files are insufficient, call \`fallback_rg\`
     at most \`max_supplementary_greps\` time(s) with specific terms, then \`graph_read\`
     at most \`max_supplementary_files\` additional file(s). Then stop.
   - \`confidence=low\` -> Call \`fallback_rg\` at most \`max_supplementary_greps\` time(s),
     then \`graph_read\` at most \`max_supplementary_files\` file(s). Then stop.

## Token Usage

A \`token-counter\` MCP is available for tracking live token usage.

- To check how many tokens a large file or text will cost **before** reading it:
  \`count_tokens({text: "<content>"})\`
- To log actual usage after a task completes (if the user asks):
  \`log_usage({input_tokens: <est>, output_tokens: <est>, description: "<task>"})\`
- To show the user their running session cost:
  \`get_session_stats()\`

Live dashboard URL is printed at startup next to "Token usage".

## Rules

- Do NOT use \`rg\`, \`grep\`, or bash file exploration before calling \`graph_continue\`.
- Do NOT do broad/recursive exploration at any confidence level.
- \`max_supplementary_greps\` and \`max_supplementary_files\` are hard caps - never exceed them.
- Do NOT dump full chat history.
- Do NOT call \`graph_retrieve\` more than once per turn.
- After edits, call \`graph_register_edit\` with the changed files. Use \`file::symbol\` notation (e.g. \`src/auth.ts::handleLogin\`) when the edit targets a specific function, class, or hook.
EOF
}

_write_policy_doc() {
  if [[ "$ASSISTANT" == "codex" ]]; then
    _write_codex_policy_doc
  else
    _write_claude_policy_doc
  fi
}

_ensure_codex_context_files

if [[ ! -f "$DOC_FILE" ]]; then
  echo "[$TOOL_LABEL] Creating $DOC_NAME ..."
  _write_policy_doc
  echo "[$TOOL_LABEL] $DOC_NAME created."
elif grep -q "graph_continue" "$DOC_FILE" && ! grep -q "$POLICY_MARKER" "$DOC_FILE"; then
  echo "[$TOOL_LABEL] Upgrading $DOC_NAME to v9 policy ..."
  _write_policy_doc
  echo "[$TOOL_LABEL] $DOC_NAME upgraded."
else
  echo "[$TOOL_LABEL] $DOC_NAME already up to date, skipping."
fi

echo "[$TOOL_LABEL] Scanning project..."
"$PYTHON" "$SCRIPT_DIR/graph_builder.py" --root "$PROJECT" --out "$DATA_DIR/info_graph.json"
echo "[$TOOL_LABEL] Scan complete."
echo ""

echo "[$TOOL_LABEL] Port    : $MCP_PORT"
echo ""

nohup env \
  DG_DATA_DIR="$DATA_DIR" \
  DUAL_GRAPH_PROJECT_ROOT="$PROJECT" \
  DG_BASE_URL="http://localhost:$MCP_PORT" \
  PORT="$MCP_PORT" \
  "$PYTHON" "$SCRIPT_DIR/mcp_graph_server.py" \
  >> "$DATA_DIR/mcp_server.log" 2>&1 &
MCP_PID=$!
echo "$MCP_PID" > "$DATA_DIR/mcp_server.pid"
echo "$MCP_PORT" > "$DATA_DIR/mcp_port"
trap 'echo ""; echo "[$TOOL_LABEL] Shutting down MCP server (PID $MCP_PID)..."; kill "$MCP_PID" 2>/dev/null; rm -f "$DATA_DIR/mcp_server.pid" "$DATA_DIR/mcp_port"' EXIT INT TERM

echo "[$TOOL_LABEL] Waiting for MCP server..."
for i in $(seq 1 20); do
  if nc -z localhost "$MCP_PORT" 2>/dev/null; then
    break
  fi
  sleep 1
done

echo "[$TOOL_LABEL] MCP server ready on port $MCP_PORT (PID $MCP_PID)."
echo ""

# ── Context hooks (Claude only) ────────────────────────────────────────────────
# Writes SessionStart + PreCompact hooks so graph context survives auto-compaction.
if [[ "$ASSISTANT" == "claude" ]]; then
  cat > "$DATA_DIR/prime.sh" << PRIMEEOF
#!/usr/bin/env bash
PORT=\$(cat "$DATA_DIR/mcp_port" 2>/dev/null || echo $MCP_PORT)
OUT=\$(curl -sf "http://localhost:\$PORT/prime" 2>/dev/null || true)
if [[ -n "\$OUT" ]]; then
  echo "\$OUT"
  echo "[dual-graph] Context loaded (port \$PORT)" >&2
else
  echo "[dual-graph] MCP server not reachable on port \$PORT — run dgc to restart" >&2
fi
PRIMEEOF
  chmod +x "$DATA_DIR/prime.sh"

  mkdir -p "$PROJECT/.claude"
  cat > "$PROJECT/.claude/settings.local.json" << SETTINGSEOF
{
  "hooks": {
    "SessionStart": [
      {"matcher": "", "hooks": [{"type": "command", "command": "$DATA_DIR/prime.sh"}]}
    ],
    "PreCompact": [
      {"matcher": "", "hooks": [{"type": "command", "command": "$DATA_DIR/prime.sh"}]}
    ]
  }
}
SETTINGSEOF
  echo "[$TOOL_LABEL] Context hooks ready (SessionStart + PreCompact)"
fi
# ──────────────────────────────────────────────────────────────────────────────

if [[ "$ASSISTANT" == "codex" ]]; then
  codex mcp remove dual-graph >/dev/null 2>&1 || true
  if codex mcp add --transport http dual-graph "http://localhost:$MCP_PORT/mcp" >/dev/null 2>&1; then
    echo "[$TOOL_LABEL] MCP config updated -> http://localhost:$MCP_PORT/mcp"
  else
    codex mcp add dual-graph --url "http://localhost:$MCP_PORT/mcp" >/dev/null 2>&1 || true
    echo "[$TOOL_LABEL] MCP config updated -> http://localhost:$MCP_PORT/mcp"
  fi
else
  claude mcp remove dual-graph >/dev/null 2>&1 || true
  claude mcp add --transport http dual-graph "http://localhost:$MCP_PORT/mcp" >/dev/null 2>&1
  echo "[$TOOL_LABEL] MCP config updated -> http://localhost:$MCP_PORT/mcp"

  # ── Token Counter MCP — local stdio via npx (persists to ~/.claude/token-counter/) ──
  # Dashboard auto-starts at http://localhost:8899 with project/session history.
  # Override with DG_TOKEN_COUNTER_URL=https://... to use a remote hosted instance instead.
  if [[ -n "${DG_TOKEN_COUNTER_URL:-}" ]]; then
    claude mcp remove token-counter >/dev/null 2>&1 || true
    claude mcp add --transport sse token-counter "${DG_TOKEN_COUNTER_URL}/sse" >/dev/null 2>&1 || true
    echo "[$TOOL_LABEL] Token counter -> ${DG_TOKEN_COUNTER_URL} (SSE)"
  else
    claude mcp remove token-counter >/dev/null 2>&1 || true
    claude mcp add token-counter -- npx -y token-counter-mcp >/dev/null 2>&1 || true
    echo "[$TOOL_LABEL] Token counter -> http://localhost:8899 (local, npx)"
  fi
  # ───────────────────────────────────────────────────────────────────────────
fi

echo ""
echo "[$TOOL_LABEL] Starting $ASSISTANT..."
echo ""

cd "$PROJECT"
if [[ -n "$PROMPT" ]]; then
  "$ASSISTANT" "$PROMPT"
else
  "$ASSISTANT"
fi
