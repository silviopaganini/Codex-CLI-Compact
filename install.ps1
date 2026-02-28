# Dual-Graph one-time setup for Windows
# Usage (PowerShell, run as normal user):
#   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$BASE = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$INSTALL_DIR = "$env:USERPROFILE\.dual-graph"

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

Write-Host "[install] Downloading core engine..."
Invoke-WebRequest "$BASE/core/mcp_graph_server.py" -OutFile "$INSTALL_DIR\mcp_graph_server.py"
Invoke-WebRequest "$BASE/core/graph_builder.py"    -OutFile "$INSTALL_DIR\graph_builder.py"
Invoke-WebRequest "$BASE/core/dg.py"               -OutFile "$INSTALL_DIR\dg.py"

Write-Host "[install] Downloading CLI wrappers..."
Invoke-WebRequest "$BASE/bin/dgc.cmd" -OutFile "$INSTALL_DIR\dgc.cmd"
Invoke-WebRequest "$BASE/bin/dg.cmd"  -OutFile "$INSTALL_DIR\dg.cmd"

Write-Host "[install] Creating Python venv..."
python -m venv "$INSTALL_DIR\venv"

Write-Host "[install] Installing Python dependencies..."
& "$INSTALL_DIR\venv\Scripts\pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet

# Add to user PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*\.dual-graph*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$INSTALL_DIR", "User")
    Write-Host "[install] Added $INSTALL_DIR to your PATH"
}

Write-Host ""
Write-Host "[install] Done! Open a NEW terminal, then per project:"
Write-Host "  dgc C:\path\to\project   # Claude Code (local MCP, fully private)"
Write-Host "  dg  C:\path\to\project   # Codex CLI   (local MCP, fully private)"
