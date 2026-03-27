try {
    # Dual-Graph one-time setup for Windows
    # Usage (PowerShell):
    #   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex

    $ErrorActionPreference = "Stop"

    $R2          = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
    $BASE_URL    = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
    $INSTALL_DIR = "$env:USERPROFILE\.dual-graph"
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
                # Use cmd rmdir first — PowerShell Remove-Item -Recurse has
                # long-standing bugs with venv directories on Windows.
                if (Test-Path $Path -PathType Container) {
                    cmd /c "rmdir /s /q `"$Path`"" 2>$null
                    if (-not (Test-Path $Path)) { return $true }
                }
                Remove-Item $Path -Recurse -Force -ErrorAction Stop
                return $true
            } catch {
                if ($attempt -ge $MaxRetries) { return $false }
                Start-Sleep -Seconds ([Math]::Min(2 * $attempt, 6))
            }
        }
        return $false
    }

    # Run an external command, suppressing stderr so $ErrorActionPreference=Stop
    # doesn't convert it into a terminating error (known PowerShell gotcha).
    function Invoke-Native {
        param([Parameter(Mandatory)][scriptblock]$Command)
        $backupEAP = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $Command 2>$null
        } finally {
            $ErrorActionPreference = $backupEAP
        }
    }

    function Ensure-Venv {
        param(
            [Parameter(Mandatory = $true)][string]$PythonExe,
            [Parameter(Mandatory = $true)][string]$InstallDir
        )
        $venvDir = Join-Path $InstallDir "venv"
        $venvPython = Join-Path $venvDir "Scripts\python.exe"
        $venvCfg = Join-Path $venvDir "pyvenv.cfg"

        # Step 1: Kill all processes holding venv files open.
        # First try targeted kill via WMI CommandLine — works for normal processes.
        # WMI CommandLine is empty for protected/system processes (e.g. Claude Code's MCP
        # server), so the targeted kill is silently a no-op in that case.
        try {
            Get-Process | Where-Object {
                try { $_.Path -and $_.Path.StartsWith($InstallDir) } catch { $false }
            } | ForEach-Object {
                try { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue } catch {}
            }
            Get-WmiObject Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
                Where-Object { $_.CommandLine -and $_.CommandLine -like "*$InstallDir*" } |
                ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
            Start-Sleep -Milliseconds 500
        } catch {}
        # Also use taskkill — it works across terminal sessions where Stop-Process gets Access Denied
        try { & taskkill /F /IM "mcp-graph-server.exe" /T 2>$null } catch {}
        try { & taskkill /F /IM "graph-builder.exe" /T 2>$null } catch {}

        # Fallback: if a venv .pyd is still locked after targeted kills, the locking process
        # returned empty WMI CommandLine (protected process, e.g. Claude Code MCP server).
        # Probe the file directly — if locked, kill ALL python.exe as a last resort.
        $probePyd = Get-ChildItem (Join-Path $venvDir "Lib\site-packages\graperoot") -Filter "*.pyd" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($probePyd) {
            $locked = $false
            try {
                $stream = [System.IO.File]::Open($probePyd.FullName, 'Open', 'ReadWrite', 'None')
                $stream.Close()
            } catch [System.IO.IOException] {
                $locked = $true
            } catch {}
            if ($locked) {
                Write-Host "[install] Venv DLL is still locked — stopping all Python processes..."
                try { & taskkill /F /IM "python.exe" /T 2>$null } catch {}
                try { & taskkill /F /IM "pythonw.exe" /T 2>$null } catch {}
                Start-Sleep -Milliseconds 1000
            }
        }

        # Step 2: Neutralise any orphaned pywin32 left by a previous installer version.
        # pip uninstall exits 0 but leaves pywin32.pth behind when the DLL is locked.
        # The leftover .pth makes every Python startup print a ModuleNotFoundError to
        # stderr, which becomes a terminating exception under EAP=Stop.
        # Fix: delete the .pth; if Windows ACLs block deletion, overwrite with empty
        # content — write permission is granted even when delete isn't.
        $sitePkgs = Join-Path $venvDir "Lib\site-packages"
        $pywin32Pth = Join-Path $sitePkgs "pywin32.pth"
        if (Test-Path $pywin32Pth) {
            Write-Host "[install] Neutralising orphaned pywin32 (left by previous install)..."
            # 1. Try deletion first
            try { Remove-Item $pywin32Pth -Force -ErrorAction Stop } catch {
                # Deletion failed — overwrite with empty content so site.py ignores it
                try { [System.IO.File]::WriteAllText($pywin32Pth, "") } catch {}
            }
            # 2. Best-effort cleanup of DLL folder (may be locked — non-fatal)
            $pw32sys = Join-Path $sitePkgs "pywin32_system32"
            if (Test-Path $pw32sys) {
                try { Remove-Item $pw32sys -Recurse -Force -ErrorAction SilentlyContinue } catch {}
            }
            # 3. pip uninstall for registry cleanup — don't depend on exit code
            Invoke-Native { & $venvPython -m pip uninstall pywin32 pywin32-ctypes -y } | Out-Null
        }

        # Step 3: Probe the existing venv — reuse only if structurally complete and pip works.
        if ((Test-Path $venvPython) -and (Test-Path $venvCfg)) {
            Invoke-Native { & $venvPython -m pip --version } | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[install] Reusing existing Python venv..."
                return
            }

            # pip is missing — venv is in bad shape; fall through to recreate it fresh
            Write-Host "[install] Existing venv is missing pip — recreating it..."
        }

        # Remove any existing (broken or partial) venv before creating fresh.
        # Use rename-then-delete so locked files don't block the new venv.
        if (Test-Path $venvDir) {
            Write-Host "[install] Removing stale venv directory..."
            $tombstone = "$venvDir._old_$(Get-Date -Format 'yyyyMMddHHmmss')"
            try {
                Rename-Item $venvDir $tombstone -Force -ErrorAction Stop
                Remove-PathWithRetry $tombstone | Out-Null
            } catch {
                # Rename failed — try direct removal
                if (-not (Remove-PathWithRetry $venvDir)) {
                    Write-Host "[install] Cannot remove locked venv. Attempting to create over it with --clear..."
                }
            }
        }

        Write-Host "[install] Creating Python venv..."
        Invoke-Native { & $PythonExe -m venv $venvDir --clear --copies }
        if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) { return }

        # Retry without --copies (some Windows installs don't support it)
        Write-Host "[install] Retrying venv creation without --copies..."
        if (Test-Path $venvDir) {
            try { Rename-Item $venvDir "$venvDir._old2" -Force -ErrorAction Stop; Remove-PathWithRetry "$venvDir._old2" | Out-Null } catch {}
        }
        Invoke-Native { & $PythonExe -m venv $venvDir --clear }
        if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) { return }

        # Final retry: bare minimum
        Write-Host "[install] Retrying with bare venv creation..."
        if (Test-Path $venvDir) {
            try { Remove-Item $venvDir -Recurse -Force -ErrorAction SilentlyContinue } catch {}
        }
        Invoke-Native { & $PythonExe -m venv $venvDir }
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
            throw "Failed to create Python virtual environment. Try manually: $PythonExe -m venv `"$venvDir`""
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
    # Helper: returns $true if a python exe is the Windows Store stub (not real Python)
    function Test-WindowsStoreStub([string]$exe) {
        try {
            $resolved = (Get-Command $exe -ErrorAction Stop).Source
            if ($resolved -like "*\WindowsApps\*") { return $true }
        } catch {}
        return $false
    }

    $pythonExe = $null
    foreach ($candidate in @("python3.11", "python3", "python")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            if (Test-WindowsStoreStub $candidate) { continue }
            $ver = & $candidate -c "import sys; print(sys.version_info[:2])" 2>$null
            if ($ver -match "3, (1[0-9]|[2-9][0-9])") { $pythonExe = $candidate; break }
        }
    }
    if (-not $pythonExe) {
        foreach ($candidate in @("python3", "python")) {
            if (Get-Command $candidate -ErrorAction SilentlyContinue) {
                if (Test-WindowsStoreStub $candidate) { continue }
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

    # ── Identity setup ────────────────────────────────────────────────────────────
    $step = "Writing identity"
    $machineId = $null
    try {
        $existingIdPath = Join-Path $env:USERPROFILE ".dual-graph\identity.json"
        if (Test-Path $existingIdPath) {
            $existingIdentity = Get-Content $existingIdPath -Raw | ConvertFrom-Json
            if ($existingIdentity.machine_id -and $existingIdentity.installed_date) {
                $machineId = "$($existingIdentity.machine_id)"
            }
        }
    } catch {}
    if (-not $machineId) { $machineId = [System.Guid]::NewGuid().ToString("N") }

    # Save identity so MCP server can ping on each startup (tracks real usage)
    try {
        $identity = @{
            machine_id     = $machineId
            platform       = "windows"
            installed_date = (Get-Date -Format "yyyy-MM-dd")
            tool           = "install-ps1"
        }
        $identity | ConvertTo-Json -Compress | Set-Content -Path "$INSTALL_DIR\identity.json" -Encoding UTF8
    } catch { }  # never block install

    # ── Download core engine ──────────────────────────────────────────────────────
    $step = "Downloading core engine"
    Write-Host "[install] Downloading core engine..."
    $launchDest = "$INSTALL_DIR\dual_graph_launch.sh"
    if (Test-Path $launchDest) {
        Write-Host "[install] Core engine already present, skipping download."
    } else {
        try {
            Invoke-WebRequestWithRetry -Uri "$R2/dual_graph_launch.sh" -OutFile $launchDest -Label "Download dual_graph_launch.sh"
        } catch {
            Write-Host "[install] R2 unreachable, falling back to GitHub..."
            Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dual_graph_launch.sh" -OutFile $launchDest -Label "Download dual_graph_launch.sh (GitHub fallback)"
        }
    }

    $step = "Downloading CLI wrappers"
    Write-Host "[install] Downloading CLI wrappers..."
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dgc.cmd"       -OutFile "$INSTALL_DIR\dgc.cmd"       -Label "Download dgc.cmd"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dg.cmd"        -OutFile "$INSTALL_DIR\dg.cmd"        -Label "Download dg.cmd"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dgc.ps1"       -OutFile "$INSTALL_DIR\dgc.ps1"       -Label "Download dgc.ps1"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/dg.ps1"        -OutFile "$INSTALL_DIR\dg.ps1"        -Label "Download dg.ps1"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/graperoot.cmd" -OutFile "$INSTALL_DIR\graperoot.cmd" -Label "Download graperoot.cmd"
    Invoke-WebRequestWithRetry -Uri "$BASE_URL/bin/graperoot.ps1" -OutFile "$INSTALL_DIR\graperoot.ps1" -Label "Download graperoot.ps1"
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
    $venvPy = "$INSTALL_DIR\venv\Scripts\python.exe"

    # Write a constraints file that blocks pywin32 permanently.
    $constraintsFile = Join-Path $INSTALL_DIR "pip-constraints.txt"
    "pywin32<0`npywin32-ctypes<0" | Set-Content $constraintsFile -Encoding UTF8

    # Use Invoke-Native for ALL pip calls — Python prints pywin32.pth errors to stderr
    # on startup even after we delete the .pth, and EAP=Stop turns that into a crash.
    Invoke-Native { & $venvPy -m pip install --upgrade pip --quiet } | Out-Null
    Invoke-Native { & $venvPy -m pip install "mcp>=1.3.0" uvicorn anyio starlette --quiet --constraint $constraintsFile } | Out-Null

    # Verify mcp is importable
    $step = "Verifying MCP import"
    $checkOut = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp; print('ok')" 2>$null
    if ($checkOut -ne "ok") {
        Write-Host "[install] Warning: mcp import check failed. Retrying with --force-reinstall..."
        & "$INSTALL_DIR\venv\Scripts\python.exe" -m pip install --force-reinstall "mcp>=1.3.0" uvicorn anyio starlette --quiet
        $checkOut = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp; print('ok')" 2>$null
        if ($checkOut -ne "ok") {
            # Capture the actual error for telemetry
            $errDetail = & "$INSTALL_DIR\venv\Scripts\python.exe" -c "import mcp" 2>&1 | Out-String
            throw "Failed to install 'mcp' Python package. Detail: $errDetail"
        }
    }

    # ── Add to user PATH ──────────────────────────────────────────────────────────
    $step = "Adding to PATH"
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    if ($userPath -notlike "*\.dual-graph*") {
        [Environment]::SetEnvironmentVariable("PATH", "$userPath;$INSTALL_DIR", "User")
        Write-Host "[install] Added $INSTALL_DIR to PATH"
    }
    # Also refresh current session PATH so dgc works immediately without reopening terminal
    if ($env:PATH -notlike "*$INSTALL_DIR*") {
        $env:PATH = "$env:PATH;$INSTALL_DIR"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Installation complete!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Run now in this terminal:" -ForegroundColor White
    Write-Host "    dgc `"C:\path\to\your\project`"              # Claude Code" -ForegroundColor White
    Write-Host "    dg  `"C:\path\to\your\project`"              # Codex CLI" -ForegroundColor White
    Write-Host "    graperoot `"C:\path\to\your\project`" --cursor   # Cursor IDE" -ForegroundColor White
    Write-Host "    graperoot `"C:\path\to\your\project`" --gemini   # Gemini CLI" -ForegroundColor White
    Write-Host ""

} catch {
    $errMessage = Normalize-NetworkError "$($_.Exception.Message)"
    Write-Host "`n[install] ERROR: Installation failed during: $step" -ForegroundColor Red
    Write-Host "[install] Details: $errMessage" -ForegroundColor Red

    Write-Host "`n[install] If you need help, please open an issue here:" -ForegroundColor Yellow
    Write-Host "[install]   https://github.com/kunal12203/Codex-CLI-Compact/issues/new" -ForegroundColor Yellow
    exit 1
}
