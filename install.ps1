# Dual-Graph one-time setup for Windows
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex
# With license key:
#   $env:DG_LICENSE_KEY="XXXX-XXXX-XXXX-XXXX"; irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$LICENSE_SERVER = "https://dual-graph-license-production.up.railway.app"
$BASE_URL       = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$INSTALL_DIR    = "$env:USERPROFILE\.dual-graph"

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

# ── License check ─────────────────────────────────────────────────────────────
Write-Host "[install] Checking license..."
$LICENSE_KEY = if ($env:DG_LICENSE_KEY) { $env:DG_LICENSE_KEY } else { "" }
$MACHINE_ID  = (Get-WmiObject Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID

$body = @{ key = $LICENSE_KEY; machine_id = $MACHINE_ID } | ConvertTo-Json
try {
    $resp = Invoke-RestMethod -Uri "$LICENSE_SERVER/validate" -Method POST `
        -ContentType "application/json" -Body $body -TimeoutSec 10
} catch {
    Write-Host "[install] Could not reach license server. Check your connection."
    exit 1
}

if (-not $resp.ok) {
    Write-Host "[install] License check failed: $($resp.error)"
    Write-Host "[install] Get your license at https://dual-graph.gumroad.com"
    Write-Host "[install] Then re-run:"
    Write-Host '  $env:DG_LICENSE_KEY="XXXX-XXXX-XXXX-XXXX"; irm ... | iex'
    exit 1
}

# ── Get file URLs from response ───────────────────────────────────────────────
$R2     = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
$files  = $resp.files
$URL_MCP    = if ($files.mcp_graph_server)  { $files.mcp_graph_server }  else { "$R2/mcp_graph_server.py" }
$URL_GRAPH  = if ($files.graph_builder)     { $files.graph_builder }     else { "$R2/graph_builder.py" }
$URL_LAUNCH = if ($files.dual_graph_launch) { $files.dual_graph_launch } else { "$R2/dual_graph_launch.sh" }
$URL_DG     = if ($files.dg)               { $files.dg }                else { "$R2/dg.py" }

# ── Download core engine ──────────────────────────────────────────────────────
Write-Host "[install] Downloading core engine..."
Invoke-WebRequest $URL_MCP    -OutFile "$INSTALL_DIR\mcp_graph_server.py"
Invoke-WebRequest $URL_GRAPH  -OutFile "$INSTALL_DIR\graph_builder.py"
Invoke-WebRequest $URL_LAUNCH -OutFile "$INSTALL_DIR\dual_graph_launch.sh"
Invoke-WebRequest $URL_DG     -OutFile "$INSTALL_DIR\dg.py"

Write-Host "[install] Downloading CLI wrappers..."
Invoke-WebRequest "$BASE_URL/bin/dgc.cmd" -OutFile "$INSTALL_DIR\dgc.cmd"
Invoke-WebRequest "$BASE_URL/bin/dg.cmd"  -OutFile "$INSTALL_DIR\dg.cmd"

Write-Host "[install] Creating Python venv..."
python -m venv "$INSTALL_DIR\venv"

Write-Host "[install] Installing Python dependencies..."
& "$INSTALL_DIR\venv\Scripts\pip" install "mcp>=1.3.0" uvicorn anyio starlette --quiet

# Add to user PATH if not already there
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*\.dual-graph*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$INSTALL_DIR", "User")
    Write-Host "[install] Added $INSTALL_DIR to PATH"
}

Write-Host ""
Write-Host "[install] Done! Open a NEW terminal, then run:"
Write-Host "  dgc `"C:\path\to\your\project`"   # Claude Code"
Write-Host "  dg  `"C:\path\to\your\project`"   # Codex CLI"
