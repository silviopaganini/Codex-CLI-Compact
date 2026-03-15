# dg - Codex CLI + dual-graph MCP launcher (PowerShell)
param(
    [Parameter(Position = 0)]
    [string]$ProjectPath = "."
)

$ErrorActionPreference = "Stop"

$DG = Join-Path $env:USERPROFILE ".dual-graph"
$Tool = "dg"
$R2 = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
$BaseUrl = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$WebhookUrl = "https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec"
$Python = Join-Path $DG "venv\Scripts\python.exe"
$NoticeFile = Join-Path $DG "last_update_notice.txt"

function Get-MachineId {
    $identityPath = Join-Path $DG "identity.json"
    try {
        if (Test-Path $identityPath) {
            $identity = Get-Content $identityPath -Raw | ConvertFrom-Json
            if ($identity.machine_id) { return "$($identity.machine_id)" }
        }
    } catch {}
    try {
        $uuid = (Get-CimInstance -ClassName Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID
        if ($uuid) { return "$uuid" }
    } catch {}
    if ($env:COMPUTERNAME) { return $env:COMPUTERNAME }
    return "unknown"
}

function Send-CliError([string]$Step, [string]$Message) {
    try {
        $payload = @{
            type          = "cli_error"
            platform      = "windows"
            machine_id    = (Get-MachineId)
            error_message = $Message
            script_step   = $Step
        }
        Invoke-RestMethod -Method Post -Uri $WebhookUrl -ContentType "application/json" -Body ($payload | ConvertTo-Json -Compress) -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

function Get-Text([string]$Uri) {
    $response = Invoke-WebRequest $Uri -UseBasicParsing -TimeoutSec 5
    $content = $response.Content
    if ($content -is [byte[]]) {
        return ([System.Text.Encoding]::UTF8.GetString($content)).Trim()
    }
    if ($content -is [System.Array]) {
        return ([System.Text.Encoding]::UTF8.GetString([byte[]]$content)).Trim()
    }
    return ([string]$content).Trim()
}

function Download-File([string]$Primary, [string]$Fallback, [string]$OutFile) {
    try {
        Invoke-WebRequest $Primary -OutFile $OutFile -UseBasicParsing -TimeoutSec 15
        return $true
    } catch {
        if ($Fallback) {
            try {
                Invoke-WebRequest $Fallback -OutFile $OutFile -UseBasicParsing -TimeoutSec 15
                return $true
            } catch {}
        }
    }
    return $false
}

function Get-FreePort {
    for ($port = 8080; $port -le 8199; $port++) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Any, $port)
            $listener.Start()
            $listener.Stop()
            return $port
        } catch {}
    }
    throw "no free port in range 8080-8199"
}

function Wait-Port([int]$Port, [int]$Tries = 20) {
    for ($i = 0; $i -lt $Tries; $i++) {
        try {
            $client = [System.Net.Sockets.TcpClient]::new()
            $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
            if ($async.AsyncWaitHandle.WaitOne(500)) {
                $client.EndConnect($async)
                $client.Close()
                return $true
            }
            $client.Close()
        } catch {}
        Start-Sleep -Seconds 1
    }
    return $false
}

function Invoke-NativeQuiet([string]$FilePath, [string[]]$Arguments) {
    $hasNativePref = Test-Path variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativePref) { $previousNativePref = $PSNativeCommandUseErrorActionPreference }
    try {
        if ($hasNativePref) { $global:PSNativeCommandUseErrorActionPreference = $false }
        & $FilePath @Arguments > $null 2>&1
        return $LASTEXITCODE
    } finally {
        if ($hasNativePref) { $global:PSNativeCommandUseErrorActionPreference = $previousNativePref }
    }
}

function Stop-McpServer([string]$PidFile, [string]$PortFile) {
    if (Test-Path $PidFile) {
        try { Stop-Process -Id ([int](Get-Content $PidFile -Raw)) -Force -ErrorAction SilentlyContinue } catch {}
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $PortFile) {
        try {
            $p = [int](Get-Content $PortFile -Raw)
            Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }
        } catch {}
        Remove-Item $PortFile -Force -ErrorAction SilentlyContinue
    }
}

function Find-Python3 {
    try {
        $p = (Get-Command python3 -ErrorAction SilentlyContinue).Source
        if ($p) {
            $ver = & python3 -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($ver -eq "True") { return $p }
        }
    } catch {}
    try {
        $p = (Get-Command python -ErrorAction SilentlyContinue).Source
        if ($p -and $p -notmatch 'WindowsApps') {
            $ver = & python -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($ver -eq "True") { return $p }
        }
    } catch {}
    try {
        $p = (Get-Command py -ErrorAction SilentlyContinue).Source
        if ($p) {
            $ver = & py -3 -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
            if ($ver -eq "True") { return "py -3" }
        }
    } catch {}
    $paths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe",
        "C:\Python310\python.exe"
    )
    foreach ($p in $paths) {
        if (Test-Path $p) {
            try {
                $ver = & $p -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
                if ($ver -eq "True") { return $p }
            } catch {}
        }
    }
    foreach ($conda in @("$env:USERPROFILE\miniconda3\python.exe", "$env:USERPROFILE\anaconda3\python.exe",
                         "C:\ProgramData\miniconda3\python.exe", "C:\ProgramData\anaconda3\python.exe")) {
        if (Test-Path $conda) {
            try {
                $ver = & $conda -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
                if ($ver -eq "True") { return $conda }
            } catch {}
        }
    }
    return $null
}

function Create-Venv([string]$PyExe, [string]$VenvDir) {
    if ($PyExe -eq "py -3") {
        $exit = Invoke-NativeQuiet "py" @("-3", "-m", "venv", $VenvDir)
        if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) { return $true }
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        $exit = Invoke-NativeQuiet "py" @("-3", "-m", "venv", "--without-pip", $VenvDir)
        if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
            try {
                $getPip = Join-Path $env:TEMP "get-pip.py"
                Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -TimeoutSec 30
                & (Join-Path $VenvDir "Scripts\python.exe") $getPip 2>$null
                if (Test-Path (Join-Path $VenvDir "Scripts\pip.exe")) { return $true }
            } catch {}
        }
        Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
        return $false
    }
    $exit = Invoke-NativeQuiet $PyExe @("-m", "venv", $VenvDir)
    if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) { return $true }
    Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    $exit = Invoke-NativeQuiet $PyExe @("-m", "venv", "--without-pip", $VenvDir)
    if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) {
        try {
            Write-Host "[$Tool] Bootstrapping pip via get-pip.py..."
            $getPip = Join-Path $env:TEMP "get-pip.py"
            Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getPip -UseBasicParsing -TimeoutSec 30
            & (Join-Path $VenvDir "Scripts\python.exe") $getPip 2>$null
            if (Test-Path (Join-Path $VenvDir "Scripts\pip.exe")) { return $true }
        } catch {}
    }
    Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    $exit = Invoke-NativeQuiet $PyExe @("-m", "virtualenv", $VenvDir)
    if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) { return $true }
    Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-NativeQuiet $PyExe @("-m", "pip", "install", "--user", "virtualenv") | Out-Null
    $exit = Invoke-NativeQuiet $PyExe @("-m", "virtualenv", $VenvDir)
    if ($exit -eq 0 -and (Test-Path (Join-Path $VenvDir "Scripts\python.exe"))) { return $true }
    Remove-Item $VenvDir -Recurse -Force -ErrorAction SilentlyContinue
    return $false
}

try {
    if (-not (Test-Path $DG)) { New-Item -ItemType Directory -Force -Path $DG | Out-Null }

    # -- Bulletproof Python venv setup --
    if (-not (Test-Path $Python)) {
        Write-Host "[$Tool] Python venv not found, setting up..."
        $foundPy = Find-Python3
        if (-not $foundPy) {
            $msg = "No Python 3.10+ found. Install from https://python.org/downloads"
            Write-Host "[$Tool] ERROR: $msg"
            Write-Host "[$Tool] After installing, close and reopen your terminal, then run dg again."
            Send-CliError "Checking prerequisites" $msg
            throw $msg
        }
        $pyVer = if ($foundPy -eq "py -3") { & py -3 --version 2>$null } else { & $foundPy --version 2>$null }
        Write-Host "[$Tool] Found $pyVer at $foundPy"

        $venvDir = Join-Path $DG "venv"
        if (Create-Venv $foundPy $venvDir) {
            Write-Host "[$Tool] Venv created."
        } else {
            $msg = "All venv creation methods failed (python=$foundPy). Install Python from https://python.org/downloads"
            Write-Host "[$Tool] ERROR: $msg"
            Send-CliError "Preparing Python environment" $msg
            throw $msg
        }

        Write-Host "[$Tool] Installing Python dependencies..."
        $pip = Join-Path $venvDir "Scripts\pip.exe"
        $pipExit = Invoke-NativeQuiet $pip @("install", "mcp>=1.3.0", "uvicorn", "anyio", "starlette", "--quiet")
        if ($pipExit -ne 0) {
            Write-Host "[$Tool] Retrying pip install..."
            $pipExit = Invoke-NativeQuiet $pip @("install", "mcp>=1.3.0", "uvicorn", "anyio", "starlette", "--quiet", "--no-cache-dir")
        }
        if ($pipExit -ne 0) {
            $msg = "pip install failed (exit $pipExit)"
            Send-CliError "Preparing Python environment" $msg
            throw $msg
        }
        Write-Host "[$Tool] Dependencies installed."
    }

    # Use Get-Item to get the canonical Windows path with correct casing
    $resolvedProject = (Get-Item -LiteralPath (Resolve-Path -LiteralPath $ProjectPath).Path).FullName

    Write-Host ""
    Write-Host "[$Tool] If you receive any errors:"
    Write-Host "[$Tool]   1. Wait 5 minutes and run dg again"
    Write-Host "[$Tool]   2. Join Discord for help: https://discord.gg/rxgVVgCh"
    Write-Host ""

    $DataDir = Join-Path $resolvedProject ".dual-graph"
    $Gitignore = Join-Path $resolvedProject ".gitignore"

    $localVer = "0"
    $versionFile = Join-Path $DG "version.txt"
    if (Test-Path $versionFile) { $localVer = (Get-Content $versionFile -Raw).Trim() }

    $remoteVer = ""
    try { $remoteVer = Get-Text "$BaseUrl/bin/version.txt" } catch {
        try { $remoteVer = Get-Text "$R2/version.txt" } catch {}
    }

    if ($remoteVer) {
        try {
            if ([version]$remoteVer -gt [version]$localVer) {
                if (-not (Test-Path $NoticeFile) -or ((Get-Content $NoticeFile -Raw).Trim() -ne $remoteVer)) {
                    Write-Host "[$Tool] New version available: $localVer -> $remoteVer"
                    Set-Content -Path $NoticeFile -Value $remoteVer -Encoding UTF8
                }
                Write-Host "[$Tool] Update available: $localVer -> $remoteVer ... updating"

                $downloads = @(
                    @{ Primary = "$BaseUrl/bin/mcp_graph_server.py"; Fallback = "$R2/mcp_graph_server.py"; Out = (Join-Path $DG "mcp_graph_server.py") },
                    @{ Primary = "$BaseUrl/bin/graph_builder.py";    Fallback = "$R2/graph_builder.py";    Out = (Join-Path $DG "graph_builder.py") },
                    @{ Primary = "$BaseUrl/bin/dual_graph_launch.sh";Fallback = "$R2/dual_graph_launch.sh";Out = (Join-Path $DG "dual_graph_launch.sh") },
                    @{ Primary = "$BaseUrl/bin/dgc.ps1";             Fallback = "$R2/dgc.ps1";            Out = (Join-Path $DG "dgc.ps1") },
                    @{ Primary = "$BaseUrl/bin/dg.ps1";              Fallback = "$R2/dg.ps1";             Out = (Join-Path $DG "dg.ps1") },
                    @{ Primary = "$BaseUrl/bin/dgc.cmd";             Fallback = "$R2/dgc.cmd";            Out = (Join-Path $DG "dgc.cmd") },
                    @{ Primary = "$BaseUrl/bin/dg.cmd";              Fallback = "$R2/dg.cmd";             Out = (Join-Path $DG "dg.cmd") }
                )
                foreach ($item in $downloads) {
                    [void](Download-File $item.Primary $item.Fallback $item.Out)
                }
                $dgPs1 = Join-Path $DG "dg.ps1"
                if ((Test-Path $dgPs1) -and (Get-Item $dgPs1).Length -gt 1024) {
                    [void](Download-File "$BaseUrl/bin/version.txt" "$R2/version.txt" (Join-Path $DG "version.txt"))
                }
                Write-Host "[$Tool] Updated to $remoteVer. Restarting..."
                $updatedScript = Join-Path $DG "dg.ps1"
                if (Test-Path $updatedScript) {
                    & $updatedScript $ProjectPath
                    exit $LASTEXITCODE
                }
            }
        } catch {}
    }

    if (Test-Path $Gitignore) {
        $content = Get-Content $Gitignore -ErrorAction SilentlyContinue
        if ($content -notcontains ".dual-graph/") {
            Add-Content -Path $Gitignore -Value ".dual-graph/"
            Write-Host "[$Tool] Added .dual-graph/ to .gitignore"
        }
    }

    if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }

    $scanErr = Join-Path $DataDir "scan_error.log"
    if (Test-Path $scanErr) { Remove-Item $scanErr -Force -ErrorAction SilentlyContinue }
    Write-Host "[$Tool] Project : $resolvedProject"
    Write-Host "[$Tool] Data    : $DataDir"
    Write-Host ""
    Write-Host "[$Tool] Scanning project..."
    & $Python (Join-Path $DG "graph_builder.py") --root $resolvedProject --out (Join-Path $DataDir "info_graph.json") 2> $scanErr
    if ($LASTEXITCODE -ne 0) {
        $tail = "no stderr captured"
        if (Test-Path $scanErr) {
            $tail = ((Get-Content $scanErr -Tail 20 -ErrorAction SilentlyContinue) -join " ") -replace '\s+', ' '
            if ($tail.Length -gt 700) { $tail = $tail.Substring(0, 700) }
        }
        Send-CliError "Scanning project" "Project scan failed in dg.ps1: $tail"
        throw "project scan failed"
    }
    if (Test-Path $scanErr) { Remove-Item $scanErr -Force -ErrorAction SilentlyContinue }
    Write-Host "[$Tool] Scan complete."
    Write-Host ""

    $pidFile = Join-Path $DataDir "mcp_server.pid"
    $portFile = Join-Path $DataDir "mcp_port"
    Stop-McpServer $pidFile $portFile

    $port = Get-FreePort
    Write-Host "[$Tool] Starting MCP server on port $port..."
    $log = Join-Path $DataDir "mcp_server.log"
    $errLog = Join-Path $DataDir "mcp_server.err.log"
    $env:DG_DATA_DIR = $DataDir
    $env:DUAL_GRAPH_PROJECT_ROOT = $resolvedProject
    $env:DG_BASE_URL = "http://localhost:$port"
    $env:DG_MCP_PORT = "$port"
    $server = Start-Process -FilePath $Python -ArgumentList @((Join-Path $DG "mcp_graph_server.py")) -RedirectStandardOutput $log -RedirectStandardError $errLog -WindowStyle Hidden -PassThru
    Set-Content -Path $pidFile -Value "$($server.Id)" -Encoding UTF8
    Set-Content -Path $portFile -Value "$port" -Encoding UTF8
    if (-not (Wait-Port -Port $port)) {
        Stop-McpServer $pidFile $portFile
        Send-CliError "Starting MCP server" "MCP server did not start in dg.ps1"
        throw "MCP server did not start"
    }
    Write-Host "[$Tool] MCP server ready on port $port."
    Write-Host ""

    # Register MCP with Codex CLI (stdio bridge via mcp-remote)
    # Codex CLI only supports stdio MCP servers, so we use mcp-remote to bridge HTTP->stdio
    Invoke-NativeQuiet "codex" @("mcp", "remove", "dual-graph") | Out-Null
    $npxCmd = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npxCmd) { $npxCmd = (Get-Command npx -ErrorAction SilentlyContinue).Source }
    if (-not $npxCmd) {
        Stop-McpServer $pidFile $portFile
        Send-CliError "Registering MCP" "npx not found - needed for mcp-remote bridge"
        Write-Host "[$Tool] Error: npx not found. Install Node.js from https://nodejs.org"
        exit 1
    }
    $mcpAddExit = Invoke-NativeQuiet "codex" @("mcp", "add", "dual-graph", "--", $npxCmd, "mcp-remote", "http://localhost:$port/mcp")
    if ($mcpAddExit -ne 0) {
        Stop-McpServer $pidFile $portFile
        Send-CliError "Registering MCP" "MCP registration failed in dg.ps1"
        Write-Host "[$Tool] Error: failed to register MCP in Codex."
        Write-Host "[$Tool] Make sure Codex CLI is installed: npm install -g @openai/codex"
        Write-Host "[$Tool] Join Discord for help: https://discord.gg/rxgVVgCh"
        exit 1
    }
    Write-Host "[$Tool] MCP registered -> http://localhost:$port/mcp (via mcp-remote)"

    Write-Host ""
    Write-Host "[$Tool] Questions, bugs, or feedback? Join the community:"
    Write-Host "[$Tool]    https://discord.gg/rxgVVgCh"
    Write-Host ""
    Write-Host "[$Tool] Starting Codex CLI..."
    Write-Host ""

    Push-Location $resolvedProject
    Remove-Item Env:\DG_MCP_PORT -ErrorAction SilentlyContinue
    $hasNativePref = Test-Path variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativePref) { $prevNativePref = $PSNativeCommandUseErrorActionPreference; $global:PSNativeCommandUseErrorActionPreference = $false }
    try {
        & codex
        $codexExit = $LASTEXITCODE
    } finally {
        Pop-Location
        if ($hasNativePref) { $global:PSNativeCommandUseErrorActionPreference = $prevNativePref }
    }

    Write-Host ""
    Write-Host "[$Tool] Cleaning up..."
    Invoke-NativeQuiet "codex" @("mcp", "remove", "dual-graph") | Out-Null
    Stop-McpServer $pidFile $portFile
    Write-Host "[$Tool] Done."
    exit $codexExit
} catch {
    $message = "$($_.Exception.Message)"
    if ($message) { Send-CliError "Launcher" $message }
    Write-Host "[$Tool] Error: $message" -ForegroundColor Red
    exit 1
}
