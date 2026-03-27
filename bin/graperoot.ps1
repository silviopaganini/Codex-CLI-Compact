# graperoot.ps1 - Windows launcher for Dual-Graph with AI tool selection
# Handles --cursor and --gemini directly.
# For --claude and --codex, delegates to dgc.ps1 / dg.ps1.
#
# Usage:
#   graperoot [path] --claude    Claude Code  (default)
#   graperoot [path] --codex     OpenAI Codex
#   graperoot [path] --cursor    Cursor IDE
#   graperoot [path] --gemini    Google Gemini CLI

param(
    [Parameter(Position = 0)] [string]$Arg0 = ".",
    [Parameter(Position = 1)] [string]$Arg1 = "",
    [Parameter(Position = 2)] [string]$Arg2 = "",
    [string]$Resume = ""
)

$ErrorActionPreference = "Continue"

# -- Help ----------------------------------------------------------------------
if ($Arg0 -in @("--help","-h","?","/?")) {
    Write-Host ""
    Write-Host "  graperoot - Dual-Graph AI tool launcher"
    Write-Host ""
    Write-Host "  Usage:"
    Write-Host "    graperoot [path] <tool> [options]"
    Write-Host ""
    Write-Host "  Tools:"
    Write-Host "    --claude    Claude Code   (shorthand: dgc [path])"
    Write-Host "    --codex     OpenAI Codex  (shorthand: dg  [path])"
    Write-Host "    --cursor    Cursor IDE"
    Write-Host "    --gemini    Google Gemini CLI"
    Write-Host "    --opencode  OpenCode"
    Write-Host ""
    Write-Host "  Options:"
    Write-Host "    --resume <id>    Resume a previous claude / codex session"
    Write-Host "    --help, -h, ?    Show this help"
    Write-Host ""
    Write-Host "  Examples:"
    Write-Host "    graperoot . --claude"
    Write-Host "    graperoot C:\my\project --cursor"
    Write-Host "    graperoot C:\my\project --gemini
    graperoot C:\my\project --opencode"
    Write-Host "    graperoot C:\my\project --claude --resume <session-id>"
    Write-Host "    dgc .                        # same as graperoot . --claude"
    Write-Host "    dg  .                        # same as graperoot . --codex"
    Write-Host ""
    exit 0
}

$DG          = Join-Path $env:USERPROFILE ".dual-graph"
$BaseUrl     = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$WebhookUrl  = "https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec"
$Tool        = "graperoot"

# -- Parse args: find assistant flag, project path, passthrough ----------------
$Assistant   = "claude"   # default
$ProjectPath = ""
$Passthrough = @()

foreach ($arg in @($Arg0, $Arg1, $Arg2)) {
    if ($arg -in @("--claude","claude"))   { $Assistant = "claude";  continue }
    if ($arg -in @("--codex","codex"))     { $Assistant = "codex";   continue }
    if ($arg -in @("--cursor","cursor"))   { $Assistant = "cursor";  continue }
    if ($arg -in @("--gemini","gemini"))   { $Assistant = "gemini";  continue }
    if ($arg -in @("--opencode","opencode")) { $Assistant = "opencode"; continue }
    if ($arg -and $arg -ne ".") {
        if ($arg.StartsWith("--")) { $Passthrough += $arg }
        elseif (-not $ProjectPath) { $ProjectPath = $arg }
        else { $Passthrough += $arg }
    }
}
if (-not $ProjectPath) { $ProjectPath = (Get-Location).Path }
$ProjectPath = (Resolve-Path $ProjectPath).Path

# -- For claude / codex: delegate to existing proven launchers -----------------
if ($Assistant -in @("claude","codex")) {
    $Ps1Name  = if ($Assistant -eq "claude") { "dgc.ps1" } else { "dg.ps1" }
    $LocalPs1 = Join-Path $DG $Ps1Name
    $ScriptPs1 = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Definition) $Ps1Name
    # Prefer local cached copy; fall back to script dir
    $Target = if (Test-Path $LocalPs1) { $LocalPs1 } elseif (Test-Path $ScriptPs1) { $ScriptPs1 } else { $null }
    if (-not $Target) {
        Write-Host "[$Tool] Downloading $Ps1Name..."
        $Target = $LocalPs1
        try {
            Invoke-WebRequest "$BaseUrl/bin/$Ps1Name" -OutFile $Target -UseBasicParsing -TimeoutSec 15
        } catch {
            Write-Host "[$Tool] ERROR: could not download $Ps1Name."
            Write-Host "[$Tool]   Run dgc or dg once first, or reinstall:"
            Write-Host "[$Tool]   irm $BaseUrl/install.ps1 | iex"
            exit 1
        }
    }
    $invokeArgs = @($ProjectPath) + $Passthrough
    if ($Resume) { $invokeArgs += "--resume"; $invokeArgs += $Resume }
    & $Target @invokeArgs
    exit $LASTEXITCODE
}

# -- Self-update (cursor / gemini path only - claude/codex update via their ps1) -
$_BaseUrl  = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$_R2       = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
$_VerFile  = Join-Path $DG "version.txt"
$_LocalVer = if (Test-Path $_VerFile) { (Get-Content $_VerFile -Raw).Trim() } else { "0" }
$_RemoteVer = ""
try { $_RemoteVer = (Invoke-WebRequest "$_BaseUrl/bin/version.txt" -UseBasicParsing -TimeoutSec 4).Content.Trim() } catch {
    try { $_RemoteVer = (Invoke-WebRequest "$_R2/version.txt" -UseBasicParsing -TimeoutSec 4).Content.Trim() } catch {}
}
if ($_RemoteVer -and ($_LocalVer -eq "0" -or ([version]$_RemoteVer -gt [version]$_LocalVer))) {
    Write-Host "[$Tool] Update available: $_LocalVer -> $_RemoteVer ... updating"
    $_updateList = @(
        @{ Src = "$_BaseUrl/bin/graperoot.ps1"; Dst = (Join-Path $DG "graperoot.ps1") },
        @{ Src = "$_BaseUrl/bin/graperoot.cmd"; Dst = (Join-Path $DG "graperoot.cmd") },
        @{ Src = "$_BaseUrl/bin/dgc.ps1";       Dst = (Join-Path $DG "dgc.ps1") },
        @{ Src = "$_BaseUrl/bin/dg.ps1";        Dst = (Join-Path $DG "dg.ps1") },
        @{ Src = "$_BaseUrl/bin/dual_graph_launch.sh"; Dst = (Join-Path $DG "dual_graph_launch.sh") },
        @{ Src = "$_R2/mcp_graph_server.py";    Dst = (Join-Path $DG "mcp_graph_server.py") }
    )
    foreach ($item in $_updateList) {
        try { Invoke-WebRequest $item.Src -OutFile $item.Dst -UseBasicParsing -TimeoutSec 15 | Out-Null } catch {}
    }
    try { $_RemoteVer | Set-Content -Path $_VerFile -Encoding UTF8 } catch {}
    Write-Host "[$Tool] Updated to $_RemoteVer. Restarting..."
    $_newScript = Join-Path $DG "graperoot.ps1"
    if (Test-Path $_newScript) {
        # Filter empty strings — splatting "" to a typed [string] param causes coercion errors
        $_restartArgs = @($Arg0, $Arg1, $Arg2) | Where-Object { $_ }
        if ($Resume) { $_restartArgs += "--resume"; $_restartArgs += $Resume }
        & $_newScript @_restartArgs; exit $LASTEXITCODE
    }
}

# -- cursor / gemini: need the full pipeline - load shared helpers from dgc.ps1 -
# Pull dgc.ps1 functions by dot-sourcing (it is designed to be safe to source)
$DgcPs1 = Join-Path $DG "dgc.ps1"
if (-not (Test-Path $DgcPs1)) {
    $DgcPs1 = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Definition) "dgc.ps1"
}
if (-not (Test-Path $DgcPs1)) {
    Write-Host "[$Tool] Downloading dgc.ps1 for shared helpers..."
    $DgcPs1 = Join-Path $DG "dgc.ps1"
    try {
        Invoke-WebRequest "$BaseUrl/bin/dgc.ps1" -OutFile $DgcPs1 -UseBasicParsing -TimeoutSec 15
    } catch {
        Write-Host "[$Tool] ERROR: could not download dgc.ps1."
        Write-Host "[$Tool]   irm $BaseUrl/install.ps1 | iex"
        exit 1
    }
}

# -- Shared helpers -------------------------------------------------------------
function Send-CliError([string]$Step, [string]$Message) {
    try {
        $payload = @{ type="cli_error"; platform="windows"; error_message=$Message; script_step=$Step }
        Invoke-RestMethod -Method Post -Uri $WebhookUrl -ContentType "application/json" `
            -Body ($payload | ConvertTo-Json -Compress) -TimeoutSec 5 -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

function Get-FreePort {
    for ($port = 8080; $port -le 8199; $port++) {
        try {
            $l = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Any, $port)
            $l.Start(); $l.Stop(); return $port
        } catch {}
    }
    throw "no free port in range 8080-8199"
}

function Wait-McpReady([int]$Port, [int]$TimeoutSec = 20) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", $Port)
            $tcp.Close()
            return $true
        } catch {}
        Start-Sleep -Milliseconds 500
    }
    return $false
}

# -- Locate Python venv (shared with dgc/dg) -----------------------------------
$Python = Join-Path $DG "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "[$Tool] ERROR: venv not found at $DG\venv"
    Write-Host "[$Tool]   Run 'dgc .' or 'dg .' once to set up the environment."
    exit 1
}

$DataDir = Join-Path $ProjectPath ".dual-graph"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

Write-Host ""
Write-Host "[$Tool] Project : $ProjectPath"
Write-Host "[$Tool] Data    : $DataDir"
Write-Host ""

# -- Build graph ----------------------------------------------------------------
$GraphExe = Join-Path $DG "venv\Scripts\graph_builder.exe"
$GraphPy  = $null
if (-not (Test-Path $GraphExe)) {
    # Find graph_builder.py from installed graperoot package
    $pkgDir = & $Python -c "import graperoot, os; print(os.path.dirname(graperoot.__file__))" 2>$null
    if ($pkgDir) {
        $candidate = Join-Path $pkgDir "graph_builder.py"
        if (Test-Path $candidate) { $GraphPy = $candidate }
    }
}
Write-Host "[$Tool] Scanning project..."
$InfoGraph = Join-Path $DataDir "info_graph.json"
try {
    if (Test-Path $GraphExe) {
        & $GraphExe --root $ProjectPath --out $InfoGraph 2>&1 | ForEach-Object { Write-Host $_ }
    } elseif ($GraphPy) {
        & $Python $GraphPy --root $ProjectPath --out $InfoGraph 2>&1 | ForEach-Object { Write-Host $_ }
    } else {
        Write-Host "[$Tool] WARNING: graph_builder not found - continuing without context graph."
    }
} catch {
    Write-Host "[$Tool] WARNING: graph scan failed - continuing without context graph."
}
Write-Host "[$Tool] Scan complete."
Write-Host ""

# -- Start MCP server -----------------------------------------------------------
$McpPort    = Get-FreePort
$McpServer  = Join-Path $DG "mcp_graph_server.py"
if (-not (Test-Path $McpServer)) {
    # Try installed graperoot package location
    $pkgDir = & $Python -c "import graperoot, os; print(os.path.dirname(graperoot.__file__))" 2>$null
    if ($pkgDir) {
        $candidate = Join-Path $pkgDir "mcp_graph_server.py"
        if (Test-Path $candidate) { $McpServer = $candidate }
    }
}
if (-not (Test-Path $McpServer)) {
    Write-Host "[$Tool] Downloading mcp_graph_server.py..."
    try { Invoke-WebRequest "$_R2/mcp_graph_server.py" -OutFile $McpServer -UseBasicParsing -TimeoutSec 30 | Out-Null } catch {}
}
$McpPortFile = Join-Path $DataDir "mcp_port"
$McpLog     = Join-Path $DataDir "mcp_server.log"
$McpPidFile = Join-Path $DataDir "mcp_server.pid"

Set-Content -Path $McpPortFile -Value $McpPort

Write-Host "[$Tool] Port    : $McpPort"
Write-Host "[$Tool] Waiting for MCP server..."

$mcpProc = Start-Process -FilePath $Python `
    -ArgumentList @($McpServer, "--port", $McpPort, "--data-dir", $DataDir) `
    -RedirectStandardOutput $McpLog -RedirectStandardError "$McpLog.err" `
    -PassThru -WindowStyle Hidden

Set-Content -Path $McpPidFile -Value $mcpProc.Id

if (-not (Wait-McpReady -Port $McpPort -TimeoutSec 20)) {
    Write-Host "[$Tool] ERROR: MCP server did not start in time."
    Stop-Process -Id $mcpProc.Id -Force -ErrorAction SilentlyContinue
    exit 1
}
Write-Host "[$Tool] MCP server ready on port $McpPort (PID $($mcpProc.Id))."
Write-Host ""

# -- Cursor: write project MCP config and open IDE -----------------------------
if ($Assistant -eq "cursor") {
    # Find cursor.exe
    $CursorBin = $null
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\cursor\Cursor.exe"),
        (Join-Path $env:LOCALAPPDATA "cursor\Cursor.exe"),
        (Join-Path $env:APPDATA "cursor\Cursor.exe"),
        "cursor"  # if on PATH
    )
    foreach ($c in $candidates) {
        if ($c -eq "cursor") {
            if (Get-Command cursor -ErrorAction SilentlyContinue) { $CursorBin = "cursor"; break }
        } elseif (Test-Path $c) {
            $CursorBin = $c; break
        }
    }
    if (-not $CursorBin) {
        Write-Host "[$Tool] ERROR: Cursor not found."
        Write-Host "[$Tool]   Install from https://www.cursor.com"
        Write-Host "[$Tool]   Then: Ctrl+Shift+P -> 'Install cursor command'"
        Stop-Process -Id $mcpProc.Id -Force -ErrorAction SilentlyContinue
        exit 1
    }

    # Write .cursor/mcp.json
    $CursorDir = Join-Path $ProjectPath ".cursor"
    New-Item -ItemType Directory -Force -Path $CursorDir | Out-Null
    $McpJson   = Join-Path $CursorDir "mcp.json"
    # Always use PSCustomObject so Add-Member works (Hashtable silently ignores it)
    $mcpServers = [PSCustomObject]@{}
    if (Test-Path $McpJson) {
        try {
            $parsed = Get-Content $McpJson -Raw | ConvertFrom-Json
            if ($parsed.mcpServers) { $mcpServers = $parsed.mcpServers }
        } catch {}
    }
    $mcpServers | Add-Member -NotePropertyName "dual-graph" `
        -NotePropertyValue ([PSCustomObject]@{ url = "http://localhost:$McpPort/mcp" }) -Force
    [PSCustomObject]@{ mcpServers = $mcpServers } | ConvertTo-Json -Depth 5 | Set-Content -Path $McpJson -Encoding UTF8

    Write-Host "[$Tool] MCP config written -> $McpJson"
    Write-Host "[$Tool] MCP URL: http://localhost:$McpPort/mcp"
    Write-Host ""
    Write-Host "[$Tool] NOTE: activate dual-graph in Cursor (one-time setup):"
    Write-Host "[$Tool]   Cursor Settings -> Tools & MCP -> enable 'dual-graph'"
    Write-Host ""
    Write-Host "[$Tool] Opening project in Cursor..."

    if ($CursorBin -eq "cursor") {
        Start-Process "cursor" -ArgumentList $ProjectPath
    } else {
        Start-Process $CursorBin -ArgumentList $ProjectPath
    }

    Write-Host "[$Tool] MCP server running on port $McpPort"
    Write-Host "[$Tool] Press Ctrl+C to stop the MCP server when you are done."
    try { $mcpProc.WaitForExit() } catch { Start-Sleep -Seconds 86400 }
}

# -- Gemini: write ~/.gemini/settings.json and launch -------------------------
if ($Assistant -eq "gemini") {
    # Auto-install gemini CLI if missing
    if (-not (Get-Command gemini -ErrorAction SilentlyContinue)) {
        Write-Host "[$Tool] gemini CLI not found - installing..."
        try {
            npm install -g "@google/gemini-cli" 2>&1 | Out-Null
        } catch {}
        if (-not (Get-Command gemini -ErrorAction SilentlyContinue)) {
            Write-Host "[$Tool] ERROR: could not auto-install gemini CLI."
            Write-Host "[$Tool]   npm install -g @google/gemini-cli"
            Stop-Process -Id $mcpProc.Id -Force -ErrorAction SilentlyContinue
            exit 1
        }
        Write-Host "[$Tool] gemini CLI installed."
    }

    # Write ~/.gemini/settings.json
    $GeminiDir  = Join-Path $env:USERPROFILE ".gemini"
    New-Item -ItemType Directory -Force -Path $GeminiDir | Out-Null
    $GeminiConf = Join-Path $GeminiDir "settings.json"
    $existing   = @{ mcpServers = @{} }
    if (Test-Path $GeminiConf) {
        try { $existing = Get-Content $GeminiConf -Raw | ConvertFrom-Json } catch {}
    }
    if (-not $existing.mcpServers) { $existing | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue @{} -Force }
    $existing.mcpServers | Add-Member -NotePropertyName "dual-graph" `
        -NotePropertyValue @{ httpUrl = "http://localhost:$McpPort/mcp" } -Force
    $existing | ConvertTo-Json -Depth 5 | Set-Content -Path $GeminiConf -Encoding UTF8

    Write-Host "[$Tool] MCP config written -> $GeminiConf"
    Write-Host "[$Tool] MCP URL: http://localhost:$McpPort/mcp"
    Write-Host ""

    Set-Location $ProjectPath
    Write-Host "[$Tool] Starting gemini..."
    Write-Host ""
    gemini
}

# -- OpenCode: write project opencode.json and launch -------------------------
if ($Assistant -eq "opencode") {
    # Auto-install opencode if missing
    if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
        Write-Host "[$Tool] opencode not found - installing..."
        try { npm install -g opencode 2>&1 | Out-Null } catch {}
        if (-not (Get-Command opencode -ErrorAction SilentlyContinue)) {
            Write-Host "[$Tool] ERROR: could not auto-install opencode."
            Write-Host "[$Tool]   npm install -g opencode"
            Stop-Process -Id $mcpProc.Id -Force -ErrorAction SilentlyContinue
            exit 1
        }
        Write-Host "[$Tool] opencode installed."
    }

    # Write MCP entry into project-level opencode.json.
    # Use Python (json.dump indent=2) instead of ConvertTo-Json because
    # PowerShell's ConvertTo-Json adds extra alignment spaces that opencode's
    # strict JSON parser rejects.
    $OpenCodeConf = Join-Path $ProjectPath "opencode.json"
    $ocMcp    = [PSCustomObject]@{}
    $ocSchema = "https://opencode.ai/config.json"
    if (Test-Path $OpenCodeConf) {
        try {
            $parsed = Get-Content $OpenCodeConf -Raw | ConvertFrom-Json
            if ($parsed.mcp)       { $ocMcp    = $parsed.mcp }
            if ($parsed.'$schema') { $ocSchema = $parsed.'$schema' }
        } catch {}
    }
    $ocMcp | Add-Member -NotePropertyName "dual-graph" `
        -NotePropertyValue ([PSCustomObject]@{ type = "remote"; url = "http://localhost:$McpPort/mcp"; enabled = $true }) -Force
    $ocOut = [PSCustomObject]@{}
    $ocOut | Add-Member -NotePropertyName '$schema' -NotePropertyValue $ocSchema
    $ocOut | Add-Member -NotePropertyName 'mcp'     -NotePropertyValue $ocMcp
    $ocJsonCompact = $ocOut | ConvertTo-Json -Depth 5 -Compress
    $pyScript = @"
import json, sys
data = json.loads(sys.argv[1])
with open(sys.argv[2], 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
"@
    & $Python -c $pyScript $ocJsonCompact $OpenCodeConf

    Write-Host "[$Tool] MCP config written -> $OpenCodeConf"
    Write-Host "[$Tool] MCP URL: http://localhost:$McpPort/mcp"
    Write-Host ""

    Set-Location $ProjectPath
    Write-Host "[$Tool] Starting opencode..."
    Write-Host ""
    opencode
}

# Cleanup
Stop-Process -Id $mcpProc.Id -Force -ErrorAction SilentlyContinue
