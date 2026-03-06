# Dual-Graph one-time setup for Windows
# Usage (PowerShell):
#   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

$ErrorActionPreference = "Stop"
$LICENSE_SERVER = "https://dual-graph-license-production.up.railway.app"
$R2          = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
$BASE_URL    = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$INSTALL_DIR = "$env:USERPROFILE\.dual-graph"

New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

# ── License check + install telemetry (same as install.sh flow) ───────────────
Write-Host "[install] Checking license..."
$licenseKey = "$env:DG_LICENSE_KEY"
$machineId = (Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID
if ([string]::IsNullOrWhiteSpace($machineId)) { $machineId = "$env:COMPUTERNAME" }
$payload = @{
    key        = $licenseKey
    machine_id = $machineId
    platform   = "windows"
    tool       = "install-ps1"
    name       = "$env:DG_NAME"
    email      = "$env:DG_EMAIL"
}
try {
    $validateResp = Invoke-RestMethod `
      -Uri "$LICENSE_SERVER/validate" `
      -Method Post `
      -ContentType "application/json" `
      -Body ($payload | ConvertTo-Json -Compress) `
      -TimeoutSec 10
} catch {
    Write-Host "[install] License check failed: server unreachable"
    exit 1
}
if (-not $validateResp.ok) {
    $err = "$($validateResp.error)"
    if ([string]::IsNullOrWhiteSpace($err)) { $err = "unknown" }
    Write-Host "[install] License check failed: $err"
    exit 1
}

# Save identity so MCP server can ping on each startup (tracks real usage)
try {
    $identity = @{ machine_id = $machineId; platform = "windows"; tool = "install-ps1" }
    $identity | ConvertTo-Json -Compress | Set-Content -Path "$INSTALL_DIR\identity.json" -Encoding UTF8
} catch { }  # never block install

# ── Download core engine ──────────────────────────────────────────────────────
Write-Host "[install] Downloading core engine..."
Invoke-WebRequest "$R2/mcp_graph_server.py"  -OutFile "$INSTALL_DIR\mcp_graph_server.py"  -UseBasicParsing
Invoke-WebRequest "$R2/graph_builder.py"     -OutFile "$INSTALL_DIR\graph_builder.py"     -UseBasicParsing
Invoke-WebRequest "$R2/dual_graph_launch.sh" -OutFile "$INSTALL_DIR\dual_graph_launch.sh" -UseBasicParsing
Invoke-WebRequest "$R2/dg.py"               -OutFile "$INSTALL_DIR\dg.py"               -UseBasicParsing

Write-Host "[install] Downloading CLI wrappers..."
Invoke-WebRequest "$BASE_URL/bin/dgc.cmd" -OutFile "$INSTALL_DIR\dgc.cmd" -UseBasicParsing
Invoke-WebRequest "$BASE_URL/bin/dg.cmd"  -OutFile "$INSTALL_DIR\dg.cmd"  -UseBasicParsing
Invoke-WebRequest "$BASE_URL/bin/dgc.ps1" -OutFile "$INSTALL_DIR\dgc.ps1" -UseBasicParsing
Invoke-WebRequest "$BASE_URL/bin/dg.ps1"  -OutFile "$INSTALL_DIR\dg.ps1"  -UseBasicParsing

# ── Find Python 3.11 (preferred) or fall back ─────────────────────────────────
Write-Host "[install] Locating Python..."
$pythonExe = $null
foreach ($candidate in @("python3.11", "python3", "python")) {
    if (Get-Command $candidate -ErrorAction SilentlyContinue) {
        $ver = & $candidate -c "import sys; print(sys.version_info[:2])" 2>$null
        if ($ver -match "3, 11") { $pythonExe = $candidate; break }
    }
}
# Fall back to any Python 3.8+ if 3.11 not found
if (-not $pythonExe) {
    foreach ($candidate in @("python3", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $pythonExe = $candidate; break
        }
    }
}
if (-not $pythonExe) {
    Write-Host "[install] Error: Python not found. Install Python 3.11 via: scoop install python311"
    exit 1
}
$verStr = & $pythonExe --version 2>&1
Write-Host "[install] Using $pythonExe ($verStr)"

# ── Create venv ───────────────────────────────────────────────────────────────
Write-Host "[install] Creating Python venv..."
& $pythonExe -m venv "$INSTALL_DIR\venv" --clear --copies

Write-Host "[install] Installing Python dependencies..."
& "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install "mcp>=1.3.0" uvicorn anyio starlette --quiet
if (Get-Command python3 -ErrorAction SilentlyContinue) {
    & python3 -m pip install --user "mcp>=1.3.0" --quiet
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python -m pip install --user "mcp>=1.3.0" --quiet
}

# Verify mcp is importable
$check = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp; print('ok')" 2>&1
if ($check -ne "ok") {
    Write-Host "[install] Warning: mcp import check failed. Retrying install..."
    & "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install "mcp>=1.3.0" uvicorn anyio starlette
}

# ── Add to user PATH ──────────────────────────────────────────────────────────
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*\.dual-graph*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$INSTALL_DIR", "User")
    Write-Host "[install] Added $INSTALL_DIR to PATH"
}

Write-Host ""
Write-Host "[install] Done! Open a NEW terminal, then run:"
Write-Host "  dgc `"C:\path\to\your\project`"   # Claude Code"
Write-Host "  dg  `"C:\path\to\your\project`"   # Codex CLI"
