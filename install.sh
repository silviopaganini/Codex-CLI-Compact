#!/usr/bin/env bash
# Dual-Graph one-time setup
# Usage: curl -sSL https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.sh | bash

set -euo pipefail

LICENSE_SERVER="https://dual-graph-license.up.railway.app"
INSTALL_DIR="$HOME/.dual-graph"
VENV="$INSTALL_DIR/venv"
mkdir -p "$INSTALL_DIR"

# ── License check (free mode: server returns public URLs, paid mode: validates key) ──
echo "[install] Checking license..."
LICENSE_KEY="${DG_LICENSE_KEY:-}"
MACHINE_ID=$(python3 -c "import uuid; print(uuid.getnode())" 2>/dev/null || echo "unknown")

VALIDATE_RESP=$(curl -sf -X POST "$LICENSE_SERVER/validate" \
  -H "Content-Type: application/json" \
  -d "{\"key\":\"$LICENSE_KEY\",\"machine_id\":\"$MACHINE_ID\"}" 2>/dev/null || echo '{"ok":false,"error":"server unreachable"}')

OK=$(echo "$VALIDATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ok','false'))" 2>/dev/null || echo "false")

if [[ "$OK" != "True" && "$OK" != "true" ]]; then
  ERR=$(echo "$VALIDATE_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error','unknown'))" 2>/dev/null || echo "unknown")
  echo "[install] License check failed: $ERR"
  echo "[install] Get your license at https://dual-graph.gumroad.com"
  echo "[install] Then re-run: DG_LICENSE_KEY=XXXX-XXXX-XXXX-XXXX curl -sSL ... | bash"
  exit 1
fi

# ── Get file URLs from license server response ────────────────────────────────
get_url() {
  echo "$VALIDATE_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
files = d.get('files', {})
print(files.get('$1', ''))
" 2>/dev/null || echo ""
}

URL_MCP=$(get_url mcp_graph_server)
URL_GRAPH=$(get_url graph_builder)
URL_LAUNCH=$(get_url dual_graph_launch)
URL_DG=$(get_url dg)

# Fallback to Cloudflare R2 if server returned empty URLs
R2="https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
BASE_URL="https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
[[ -z "$URL_MCP"    ]] && URL_MCP="$R2/mcp_graph_server.py"
[[ -z "$URL_GRAPH"  ]] && URL_GRAPH="$R2/graph_builder.py"
[[ -z "$URL_LAUNCH" ]] && URL_LAUNCH="$R2/dual_graph_launch.sh"
[[ -z "$URL_DG"     ]] && URL_DG="$R2/dg.py"

# ── Download core engine ──────────────────────────────────────────────────────
echo "[install] Downloading core engine..."
curl -sSL "$URL_MCP"    -o "$INSTALL_DIR/mcp_graph_server.py"
curl -sSL "$URL_GRAPH"  -o "$INSTALL_DIR/graph_builder.py"
curl -sSL "$URL_LAUNCH" -o "$INSTALL_DIR/dual_graph_launch.sh" && chmod +x "$INSTALL_DIR/dual_graph_launch.sh"
curl -sSL "$URL_DG"     -o "$INSTALL_DIR/dg.py"

echo "[install] Downloading CLI tools..."
curl -sSL "$BASE_URL/bin/dgc" -o "$INSTALL_DIR/dgc" && chmod +x "$INSTALL_DIR/dgc"
curl -sSL "$BASE_URL/bin/dg"  -o "$INSTALL_DIR/dg"  && chmod +x "$INSTALL_DIR/dg"

echo "[install] Creating Python venv at $VENV ..."
python3 -m venv "$VENV"

echo "[install] Installing Python dependencies..."
"$VENV/bin/pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet

# Add to PATH if not already there
SHELL_RC="$HOME/.zshrc"
[[ "$SHELL" == */bash ]] && SHELL_RC="$HOME/.bashrc"
if ! grep -q '.dual-graph' "$SHELL_RC" 2>/dev/null; then
  echo 'export PATH="$PATH:$HOME/.dual-graph"' >> "$SHELL_RC"
  echo "[install] Added ~/.dual-graph to PATH in $SHELL_RC"
fi

echo ""
echo "[install] Done! Run once:"
echo "  source $SHELL_RC"
echo ""
echo "Then per project:"
echo "  dgc /path/to/project   # Claude Code (local MCP, fully private)"
echo "  dg  /path/to/project   # Codex CLI   (local MCP, fully private)"
