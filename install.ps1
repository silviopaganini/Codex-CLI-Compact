try {
    # Dual-Graph one-time setup for Windows
    # Usage (PowerShell):
    #   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

    $ErrorActionPreference = "Stop"
    $LICENSE_SERVER = "https://dual-graph-license-production.up.railway.app"
    $R2          = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
    $BASE_URL    = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
    $INSTALL_DIR = "$env:USERPROFILE\.dual-graph"
    $WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec"

    # Prefer modern TLS to avoid intermittent "underlying connection was closed" failures.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
    } catch {
        try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}
    }

    function Normalize-NetworkError([string]$message) {
        if ([string]::IsNullOrWhiteSpace($message)) { return "unknown network error" }
        if ($message -match "Connessione sottostante chiusa") {
            return "Underlying connection was closed: unexpected failure during a send operation."
        }
        return $message
    }

    function Invoke-WebRequestWithRetry {
        param(
            [Parameter(Mandatory = $true)][string]$Uri,
            [Parameter(Mandatory = $true)][string]$OutFile,
            [Parameter(Mandatory = $true)][string]$Label,
            [int]$MaxRetries = 4,
            [int]$TimeoutSec = 30
        )
        for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
            try {
                Invoke-WebRequest $Uri -OutFile $OutFile -UseBasicParsing -TimeoutSec $TimeoutSec
                return
            } catch {
                if ($attempt -ge $MaxRetries) {
                    $raw = "$($_.Exception.Message)"
                    $norm = Normalize-NetworkError $raw
                    throw "$Label failed after $MaxRetries attempts: $norm"
                }
                Start-Sleep -Seconds ([Math]::Min(2 * $attempt, 8))
            }
        }
    }

    function Remove-PathWithRetry {
        param(
            [Parameter(Mandatory = $true)][string]$Path,
            [int]$MaxRetries = 4
        )
        if (-not (Test-Path $Path)) { return $true }
        for ($attempt = 1; $attempt -le $MaxRetries; $attempt++) {
            try {
                Remove-Item $Path -Recurse -Force -ErrorAction Stop
                return $true
            } catch {
                if ($attempt -ge $MaxRetries) { return $false }
                Start-Sleep -Seconds ([Math]::Min(2 * $attempt, 6))
            }
        }
        return $false
    }

    function Ensure-Venv {
        param(
            [Parameter(Mandatory = $true)][string]$PythonExe,
            [Parameter(Mandatory = $true)][string]$InstallDir
        )
        $venvDir = Join-Path $InstallDir "venv"
        $venvPython = Join-Path $venvDir "Scripts\python.exe"
        $venvLooksHealthy = $false

        if (Test-Path $venvPython) {
            & $venvPython -m pip --version > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[install] Reusing existing Python venv..."
                return
            }

            Write-Host "[install] Existing venv is missing pip. Trying to repair it..."
            & $venvPython -m ensurepip --upgrade > $null 2>&1
            & $venvPython -m pip --version > $null 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[install] Repaired existing Python venv."
                return
            }

            Write-Host "[install] Existing venv is incomplete. Rebuilding it..."
            if (-not (Remove-PathWithRetry $venvDir)) {
                throw "Could not remove broken virtual environment at $venvDir. Close terminals or Python processes using ~/.dual-graph and retry."
            }
        }

        Write-Host "[install] Creating Python venv..."
        & $PythonExe -m venv $venvDir --copies
        if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) { return }

        Write-Host "[install] Fresh venv creation failed. Cleaning up partial environment and retrying..."
        if (-not (Remove-PathWithRetry $venvDir)) {
            throw "Could not remove locked virtual environment at $venvDir. Close terminals or Python processes using ~/.dual-graph and retry."
        }

        & $PythonExe -m venv $venvDir --copies
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw "Failed to create Python virtual environment"
        }
    }

    # Helper: ask user Y/n, default Y. Returns $true if yes.
    function Confirm-Install([string]$prompt) {
        $answer = Read-Host "$prompt [Y/n]"
        if ($answer -match '^\s*[Nn]') { return $false }
        return $true
    }

    # ══════════════════════════════════════════════════════════════════════════════
    # PREREQUISITE CHECK — detect missing tools, ask user, install or stop
    # ══════════════════════════════════════════════════════════════════════════════
    $step = "Checking prerequisites"
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "  Dual-Graph Installer" -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""

    $hasWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
    $needsRestart = $false

    # ── Check Python ──────────────────────────────────────────────────────────────
    $pythonExe = $null
    foreach ($candidate in @("python3.11", "python3", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $ver = & $candidate -c "import sys; print(sys.version_info[:2])" 2>$null
            if ($ver -match "3, (1[0-9]|[2-9][0-9])") { $pythonExe = $candidate; break }
        }
    }
    if (-not $pythonExe) {
        foreach ($candidate in @("python3", "python")) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                $ver = & $candidate -c "import sys; print(sys.version_info[:2])" 2>$null
                if ($ver -match "3,") { $pythonExe = $candidate; break }
            }
        }
    }

    if ($pythonExe) {
        $verStr = & $pythonExe --version 2>&1
        Write-Host "[check] Python found: $verStr" -ForegroundColor Green
    } else {
        Write-Host "[check] Python is NOT installed." -ForegroundColor Yellow
        if ($hasWinget) {
            if (Confirm-Install "[check] Install Python 3.11 via winget?") {
                Write-Host "[install] Installing Python 3.11..."
                winget install Python.Python.3.11 --accept-source-agreements --accept-package-agreements --silent
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[install] Python 3.11 installed." -ForegroundColor Green
                    $needsRestart = $true
                } else {
                    Write-Host "[install] Python install failed. Install manually from https://python.org" -ForegroundColor Red
                    Write-Host "[install] Then run this installer again."
                    exit 1
                }
            } else {
                Write-Host ""
                Write-Host "[install] Python is required. Install it manually, then run this installer again:" -ForegroundColor Yellow
                Write-Host "  winget install Python.Python.3.11" -ForegroundColor White
                Write-Host "  (or download from https://python.org)" -ForegroundColor White
                exit 0
            }
        } else {
            Write-Host "[check] winget not available for automatic install." -ForegroundColor Yellow
            Write-Host "[install] Please install Python 3.11 manually from https://python.org" -ForegroundColor Yellow
            Write-Host "[install] Then run this installer again."
            exit 0
        }
    }

    # ── Check Node.js ─────────────────────────────────────────────────────────────
    $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
    if ($nodeCmd) {
        $nodeVer = & node --version 2>&1
        Write-Host "[check] Node.js found: $nodeVer" -ForegroundColor Green
    } else {
        Write-Host "[check] Node.js is NOT installed." -ForegroundColor Yellow
        if ($hasWinget) {
            if (Confirm-Install "[check] Install Node.js LTS via winget?") {
                Write-Host "[install] Installing Node.js LTS..."
                winget install OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements --silent
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[install] Node.js installed." -ForegroundColor Green
                    $needsRestart = $true
                } else {
                    Write-Host "[install] Node.js install failed. Install manually from https://nodejs.org" -ForegroundColor Red
                    Write-Host "[install] Then run this installer again."
                    exit 1
                }
            } else {
                Write-Host ""
                Write-Host "[install] Node.js is required. Install it manually, then run this installer again:" -ForegroundColor Yellow
                Write-Host "  winget install OpenJS.NodeJS.LTS" -ForegroundColor White
                Write-Host "  (or download from https://nodejs.org)" -ForegroundColor White
                exit 0
            }
        } else {
            Write-Host "[check] winget not available for automatic install." -ForegroundColor Yellow
            Write-Host "[install] Please install Node.js LTS from https://nodejs.org" -ForegroundColor Yellow
            Write-Host "[install] Then run this installer again."
            exit 0
        }
    }

    # ── If we just installed Python or Node, user must restart terminal ───────────
    if ($needsRestart) {
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Cyan
        Write-Host "  Prerequisites installed!" -ForegroundColor Green
        Write-Host "  Close this terminal, open a NEW one," -ForegroundColor Yellow
        Write-Host "  and run this installer again:" -ForegroundColor Yellow
        Write-Host "" -ForegroundColor Yellow
        Write-Host "  irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex" -ForegroundColor White
        Write-Host "========================================" -ForegroundColor Cyan
        exit 0
    }

    # ── Check Claude Code ─────────────────────────────────────────────────────────
    $claudeCmd = Get-Command claude -ErrorAction SilentlyContinue
    if ($claudeCmd) {
        Write-Host "[check] Claude Code found." -ForegroundColor Green
    } else {
        Write-Host "[check] Claude Code is NOT installed." -ForegroundColor Yellow
        $npmCmd = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
        if (-not $npmCmd) { $npmCmd = (Get-Command npm -ErrorAction SilentlyContinue).Source }
        if ($npmCmd) {
            if (Confirm-Install "[check] Install Claude Code via npm?") {
                Write-Host "[install] Installing Claude Code..."
                & $npmCmd install -g "@anthropic-ai/claude-code" 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "[install] Claude Code installed." -ForegroundColor Green
                } else {
                    Write-Host "[install] Warning: Claude Code install failed. You can install it later:" -ForegroundColor Yellow
                    Write-Host "  npm install -g @anthropic-ai/claude-code" -ForegroundColor White
                }
            } else {
                Write-Host "[install] You can install Claude Code later:" -ForegroundColor Yellow
                Write-Host "  npm install -g @anthropic-ai/claude-code" -ForegroundColor White
            }
        } else {
            Write-Host "[install] npm not found. Install Claude Code later after Node.js is on PATH:" -ForegroundColor Yellow
            Write-Host "  npm install -g @anthropic-ai/claude-code" -ForegroundColor White
        }
    }

    Write-Host ""
    Write-Host "[install] All prerequisites satisfied. Installing dual-graph..." -ForegroundColor Green
    Write-Host ""

    # ══════════════════════════════════════════════════════════════════════════════
    # MAIN INSTALL — same as before
    # ══════════════════════════════════════════════════════════════════════════════

    $step = "Initializing install directory"
    New-Item -ItemType Directory -Force -Path $INSTALL_DIR | Out-Null

    # ── License check + install telemetry (same as install.sh flow) ───────────────
    $step = "Checking license"
    Write-Host "[install] Checking license..."
    $licenseKey = "$env:DG_LICENSE_KEY"
    $machineId = (Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID
    if ([string]::IsNullOrWhiteSpace($machineId)) { $machineId = "$env:COMPUTERNAME" }
    $payload = @{
        key        = $licenseKey
        machine_id = $machineId
        platform   = "windows"
        tool       = "install-ps1"
    }
    $licenseOk = $false
    try {
        $validateResp = Invoke-RestMethod `
          -Uri "$LICENSE_SERVER/validate" `
          -Method Post `
          -ContentType "application/json" `
          -Body ($payload | ConvertTo-Json -Compress) `
          -TimeoutSec 10
        if ($validateResp.ok) {
            $licenseOk = $true
            Write-Host "[install] License validated." -ForegroundColor Green
        } else {
            $err = "$($validateResp.error)"
            if ([string]::IsNullOrWhiteSpace($err)) { $err = "unknown" }
            Write-Host "[install] License check returned: $err" -ForegroundColor Yellow
            Write-Host "[install] Continuing installation..." -ForegroundColor Yellow
        }
    } catch {
        Write-Host "[install] License server unreachable — skipping check." -ForegroundColor Yellow
        Write-Host "[install] Continuing installation..." -ForegroundColor Yellow
    }

    # Save identity so MCP server can ping on each startup (tracks real usage)
    try {
        $identity = @{
            machine_id = $machineId
            platform   = "windows"
            tool       = "install-ps1"
        }
        $identity | ConvertTo-Json -Compress | Set-Content -Path "$INSTALL_DIR\identity.json" -Encoding UTF8
    } catch { }  # never block install

    # ── Download core engine ──────────────────────────────────────────────────────
    $step = "Downloading core engine"
    Write-Host "[install] Downloading core engine..."
    Invoke-WebRequestWithRetry -Uri "$R2/mcp_graph_server.py"  -OutFile "$INSTALL_DIR\mcp_graph_server.py"  -Label "Download mcp_graph_server.py"
    Invoke-WebRequestWithRetry -Uri "$R2/graph_builder.py"     -OutFile "$INSTALL_DIR\graph_builder.py"     -Label "Download graph_builder.py"
    Invoke-WebRequestWithRetry -Uri "$R2/dual_graph_launch.sh" -OutFile "$INSTALL_DIR\dual_graph_launch.sh" -Label "Download dual_graph_launch.sh"
    Invoke-WebRequestWithRetry -Uri "$R2/dg.py"                -OutFile "$INSTALL_DIR\dg.py"                -Label "Download dg.py"

    $step = "Downloading CLI wrappers"
    Write-Host "[install] Downloading CLI wrappers..."
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dgc.cmd" -OutFile "$INSTALL_DIR\dgc.cmd" -Label "Download dgc.cmd"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dg.cmd"  -OutFile "$INSTALL_DIR\dg.cmd"  -Label "Download dg.cmd"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dgc.ps1" -OutFile "$INSTALL_DIR\dgc.ps1" -Label "Download dgc.ps1"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dg.ps1"  -OutFile "$INSTALL_DIR\dg.ps1"  -Label "Download dg.ps1"
    try {
        Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/version.txt" -OutFile "$INSTALL_DIR\version.txt" -Label "Download version.txt"
    } catch {
        try { Invoke-WebRequestWithRetry -Uri "$R2/version.txt" -OutFile "$INSTALL_DIR\version.txt" -Label "Download version.txt fallback" } catch {}
    }

    # ── Re-locate Python (may have been installed earlier in this session) ────────
    $step = "Locating Python"
    if (-not $pythonExe) {
        foreach ($candidate in @("python3.11", "python3", "python")) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                $pythonExe = $candidate; break
            }
        }
    }
    if (-not $pythonExe) {
        throw "Python not found. Close this terminal, open a new one, and run the installer again."
    }
    $verStr = & $pythonExe --version 2>&1
    Write-Host "[install] Using $pythonExe ($verStr)"

    # ── Create venv ───────────────────────────────────────────────────────────────
    $step = "Creating Python venv"
    Ensure-Venv -PythonExe $pythonExe -InstallDir $INSTALL_DIR

    $step = "Installing Python dependencies"
    Write-Host "[install] Installing Python dependencies..."
    & "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install "mcp>=1.3.0" uvicorn anyio starlette --quiet
    if (Get-Command python3 -ErrorAction SilentlyContinue) {
        & python3 -m pip install --user "mcp>=1.3.0" --quiet
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m pip install --user "mcp>=1.3.0" --quiet
    }

    # Verify mcp is importable
    $step = "Verifying MCP import"
    $check = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp; print('ok')" 2>&1
    if ($check -ne "ok") {
        Write-Host "[install] Warning: mcp import check failed. Retrying install..."
        & "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install "mcp>=1.3.0" uvicorn anyio starlette
        $check = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp; print('ok')" 2>&1
        if ($check -ne "ok") {
            throw "Failed to install 'mcp' Python package."
        }
    }

    # ── Add to user PATH ──────────────────────────────────────────────────────────
    $step = "Adding to PATH"
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*\.dual-graph*") {
        [Environment]::SetEnvironmentVariable("PATH", "$userPath;$INSTALL_DIR", "User")
        Write-Host "[install] Added $INSTALL_DIR to PATH"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Installation complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Open a NEW terminal, then run:" -ForegroundColor White
    Write-Host "    dgc `"C:\path\to\your\project`"   # Claude Code" -ForegroundColor White
    Write-Host "    dg  `"C:\path\to\your\project`"   # Codex CLI" -ForegroundColor White
    Write-Host ""

} catch {
    $errMessage = Normalize-NetworkError "$($_.Exception.Message)"
    Write-Host "`n[install] ERROR: Installation failed during: $step" -ForegroundColor Red
    Write-Host "[install] Details: $errMessage" -ForegroundColor Red

    # Try to send telemetry
    try {
        $machineId = (Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID
        if ([string]::IsNullOrWhiteSpace($machineId)) { $machineId = "$env:COMPUTERNAME" }

        $errorPayload = @{
            type          = "install_error"
            platform      = "windows"
            machine_id    = $machineId
            error_message = $errMessage
            script_step   = $step
        }

        Invoke-RestMethod -Uri $WEBHOOK_URL -Method Post -ContentType "application/json" -Body ($errorPayload | ConvertTo-Json -Compress) -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
    } catch {
        # Ignore reporting errors
    }

    Write-Host "`n[install] We've logged this error, but if you need help, please open an issue here:" -ForegroundColor Yellow
    Write-Host "[install]   https://github.com/kunal12203/Codex-CLI-Compact/issues/new" -ForegroundColor Yellow
    exit 1
}
