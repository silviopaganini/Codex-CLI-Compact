# dgc — Claude Code + dual-graph MCP launcher (PowerShell)
param(
    [Parameter(Position = 0)]
    [string]$ProjectPath = "."
)

$ErrorActionPreference = "Stop"

$DG = Join-Path $env:USERPROFILE ".dual-graph"
$Tool = "dgc"
$PolicyMarker = "dgc-policy-v10"
$R2 = "https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
$BaseUrl = "https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
$WebhookUrl = "https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec"
$Python = Join-Path $DG "venv\Scripts\python.exe"
$NoticeFile = Join-Path $DG "last_update_notice.txt"
$FeedbackUrl = "https://script.google.com/macros/s/AKfycbzsOnvAiDTdhDaW73ErztJztPqT25WOCFn29VzrRYZRhBUIwHRu677DoATctAEiq6dp4Q/exec"

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
    for ($port = 8080; $port -le 8099; $port++) {
        try {
            $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $port)
            $listener.Start()
            $listener.Stop()
            return $port
        } catch {}
    }
    throw "no free port in range 8080-8099"
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

function To-ForwardSlashes([string]$Path) {
    return $Path -replace '\\', '/'
}

function Ensure-Line([string]$File, [string]$Line) {
    if (-not (Test-Path $File)) { return }
    $content = Get-Content $File -ErrorAction SilentlyContinue
    if ($content -notcontains $Line) {
        Add-Content -Path $File -Value $Line
        Write-Host "[$Tool] Added $Line to $(Split-Path $File -Leaf)"
    }
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

function Invoke-NativeCapture([string]$FilePath, [string[]]$Arguments) {
    $hasNativePref = Test-Path variable:PSNativeCommandUseErrorActionPreference
    if ($hasNativePref) { $previousNativePref = $PSNativeCommandUseErrorActionPreference }
    try {
        if ($hasNativePref) { $global:PSNativeCommandUseErrorActionPreference = $false }
        return & $FilePath @Arguments 2>$null
    } finally {
        if ($hasNativePref) { $global:PSNativeCommandUseErrorActionPreference = $previousNativePref }
    }
}

function Has-ClaudeMcp([string]$Name) {
    try {
        $list = Invoke-NativeCapture "claude" @("mcp", "list")
        if ($null -eq $list) { return $false }
        return ($list -join "`n") -match ("(?i)\b" + [regex]::Escape($Name) + "\b")
    } catch {
        return $false
    }
}

try {
    if (-not (Test-Path $DG)) { New-Item -ItemType Directory -Force -Path $DG | Out-Null }
    if (-not (Test-Path $Python)) { throw "Python environment not found. Please reinstall dual-graph once." }

    $resolvedProject = (Resolve-Path -LiteralPath $ProjectPath).Path
    $DataDir = Join-Path $resolvedProject ".dual-graph"
    $DocFile = Join-Path $resolvedProject "CLAUDE.md"
    $Gitignore = Join-Path $resolvedProject ".gitignore"

    $localVer = "0"
    $versionFile = Join-Path $DG "version.txt"
    if (Test-Path $versionFile) { $localVer = (Get-Content $versionFile -Raw).Trim() }

    $remoteVer = ""
    try { $remoteVer = Get-Text "$BaseUrl/bin/version.txt" } catch {
        try { $remoteVer = Get-Text "$R2/version.txt" } catch {}
    }

    $forcePolicyWrite = $false
    if ($remoteVer) {
        try {
            if ([version]$remoteVer -gt [version]$localVer) {
                $forcePolicyWrite = $true
                if (-not (Test-Path $NoticeFile) -or ((Get-Content $NoticeFile -Raw).Trim() -ne $remoteVer)) {
                    Write-Host "[$Tool] New version available: $localVer -> $remoteVer"
                    Set-Content -Path $NoticeFile -Value $remoteVer -Encoding UTF8
                }
                Write-Host "[$Tool] Update available: $localVer -> $remoteVer ... updating"

                $downloads = @(
                    @{ Primary = "$BaseUrl/bin/mcp_graph_server.py"; Fallback = "$R2/mcp_graph_server.py"; Out = (Join-Path $DG "mcp_graph_server.py") },
                    @{ Primary = "$BaseUrl/bin/graph_builder.py";    Fallback = "$R2/graph_builder.py";    Out = (Join-Path $DG "graph_builder.py") },
                    @{ Primary = "$BaseUrl/bin/dual_graph_launch.sh";Fallback = "$R2/dual_graph_launch.sh";Out = (Join-Path $DG "dual_graph_launch.sh") },
                    @{ Primary = "$BaseUrl/bin/dgc.ps1";             Fallback = "";                        Out = (Join-Path $DG "dgc.ps1") },
                    @{ Primary = "$BaseUrl/bin/dg.ps1";              Fallback = "";                        Out = (Join-Path $DG "dg.ps1") },
                    @{ Primary = "$BaseUrl/bin/dgc.cmd";             Fallback = "$R2/dgc.cmd";            Out = (Join-Path $DG "dgc.cmd") },
                    @{ Primary = "$BaseUrl/bin/dg.cmd";              Fallback = "$R2/dg.cmd";             Out = (Join-Path $DG "dg.cmd") },
                    @{ Primary = "$BaseUrl/bin/version.txt";         Fallback = "$R2/version.txt";        Out = (Join-Path $DG "version.txt") }
                )
                foreach ($item in $downloads) {
                    [void](Download-File $item.Primary $item.Fallback $item.Out)
                }
                Write-Host "[$Tool] Updated to $remoteVer."
            }
        } catch {}
    }

    if (Test-Path $Gitignore) { Ensure-Line $Gitignore ".dual-graph/" }

    $needWrite = $forcePolicyWrite -or -not (Test-Path $DocFile)
    if ((-not $needWrite) -and (Test-Path $DocFile)) {
        $needWrite = -not (Select-String -Path $DocFile -SimpleMatch $PolicyMarker -Quiet -ErrorAction SilentlyContinue)
    }

    if ($needWrite) {
        Write-Host "[$Tool] Writing CLAUDE.md policy..."
        try {
            $template = Get-Text "$BaseUrl/CLAUDE.md.template"
        } catch {
            $template = Get-Text "$R2/CLAUDE.md.template"
        }
        Set-Content -Path $DocFile -Value $template -Encoding UTF8
        Write-Host "[$Tool] CLAUDE.md written."
    } else {
        Write-Host "[$Tool] CLAUDE.md already up to date, skipping."
    }

    if (-not (Test-Path $DataDir)) { New-Item -ItemType Directory -Force -Path $DataDir | Out-Null }
    $contextStore = Join-Path $DataDir "context-store.json"
    if (-not (Test-Path $contextStore)) { Set-Content -Path $contextStore -Value "[]" -Encoding UTF8 }

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
        Send-CliError "Scanning project" "Project scan failed in dgc.ps1: $tail"
        throw "project scan failed"
    }
    if (Test-Path $scanErr) { Remove-Item $scanErr -Force -ErrorAction SilentlyContinue }
    Write-Host "[$Tool] Scan complete."
    Write-Host ""

    $pidFile = Join-Path $DataDir "mcp_server.pid"
    $portFile = Join-Path $DataDir "mcp_port"
    if (Test-Path $pidFile) {
        try {
            Stop-Process -Id ([int](Get-Content $pidFile -Raw)) -Force -ErrorAction SilentlyContinue
        } catch {}
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $portFile) {
        try {
            $oldPort = [int](Get-Content $portFile -Raw)
            Get-NetTCPConnection -LocalPort $oldPort -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item $portFile -Force -ErrorAction SilentlyContinue
    }

    $port = Get-FreePort
    Write-Host "[$Tool] Starting MCP server on port $port..."
    $log = Join-Path $DataDir "mcp_server.log"
    $errLog = Join-Path $DataDir "mcp_server.err.log"
    $env:DG_DATA_DIR = $DataDir
    $env:DUAL_GRAPH_PROJECT_ROOT = $resolvedProject
    $env:DG_BASE_URL = "http://localhost:$port"
    $env:PORT = "$port"
    $server = Start-Process -FilePath $Python -ArgumentList @((Join-Path $DG "mcp_graph_server.py")) -RedirectStandardOutput $log -RedirectStandardError $errLog -WindowStyle Hidden -PassThru
    Set-Content -Path $pidFile -Value "$($server.Id)" -Encoding UTF8
    Set-Content -Path $portFile -Value "$port" -Encoding UTF8
    if (-not (Wait-Port -Port $port)) {
        Send-CliError "Starting MCP server" "MCP server did not start in dgc.ps1"
        throw "MCP server did not start"
    }
    Write-Host "[$Tool] MCP server ready on port $port."
    Write-Host ""

    # PowerShell 7 can treat non-zero native exits as terminating errors.
    # Handle Claude CLI exits explicitly so "not found" on remove stays harmless.
    if (Has-ClaudeMcp "dual-graph") {
        [void](Invoke-NativeQuiet "claude" @("mcp", "remove", "dual-graph"))
    }
    $mcpAddExit = Invoke-NativeQuiet "claude" @("mcp", "add", "--transport", "http", "dual-graph", "http://localhost:$port/mcp")
    if ($mcpAddExit -ne 0) {
        $mcpAddExit = Invoke-NativeQuiet "claude" @("mcp", "add", "dual-graph", "--url", "http://localhost:$port/mcp")
    }
    if ($mcpAddExit -ne 0) {
        Send-CliError "Registering MCP" "MCP registration failed in dgc.ps1"
        Write-Host "[$Tool] Error: failed to register MCP in Claude."
        Write-Host "[$Tool] Try this:"
        Write-Host "[$Tool] 1. Update Claude Code CLI:"
        Write-Host "[$Tool]    npm install -g @anthropic-ai/claude-code"
        Write-Host "[$Tool] 2. Wait 5 minutes and run dgc again."
        Write-Host "[$Tool] 3. If it still fails, open an issue on GitHub or join Discord:"
        Write-Host "[$Tool]    https://discord.gg/rxgVVgCh"
        exit 1
    }
    Write-Host "[$Tool] MCP registered -> http://localhost:$port/mcp"

    if (-not (Has-ClaudeMcp "token-counter")) {
        # Windows: use cmd /c and a fully-qualified npx path so MCP inherits PATH correctly.
    $npxCmd = (Get-Command npx.cmd -ErrorAction SilentlyContinue).Source
    if (-not $npxCmd) {
        $npxCmd = (Get-Command npx -ErrorAction SilentlyContinue).Source
    }
    if (-not $npxCmd) { $npxCmd = "npx.cmd" }
    [void](Invoke-NativeQuiet "claude" @("mcp", "add", "--scope", "user", "token-counter", "--", "cmd", "/c", $npxCmd, "-y", "token-counter-mcp"))
        Write-Host "[$Tool] Token counter registered (global)"
    } else {
        Write-Host "[$Tool] Token counter already registered (global)"
    }

    $primePs1 = Join-Path $DataDir "prime.ps1"
    $stopPs1 = Join-Path $DataDir "stop_hook.ps1"
    $settingsDir = Join-Path $resolvedProject ".claude"
    $settingsFile = Join-Path $settingsDir "settings.local.json"

    @"
$port = if (Test-Path '$portFile') { Get-Content '$portFile' } else { '$port' }
try {
    $out = (Invoke-WebRequest "http://localhost:$port/prime" -UseBasicParsing -TimeoutSec 3).Content
    if ($out) { Write-Output $out; Write-Error "[dual-graph] Context loaded (port $port)" }
} catch {
    Write-Error "[dual-graph] MCP server not reachable on port $port -- run dgc to restart"
}
$ctxFile = '$resolvedProject\CONTEXT.md'
if (Test-Path $ctxFile) { Write-Output ""; Write-Output "=== CONTEXT.md ==="; Get-Content $ctxFile -Raw; Write-Output "=== end CONTEXT.md ===" }
$storeFile = '$contextStore'
if (Test-Path $storeFile) {
    $cutoff = (Get-Date).AddDays(-7).ToString('yyyy-MM-dd')
    try {
        $entries = (Get-Content $storeFile -Raw | ConvertFrom-Json) | Where-Object { $_.date -ge $cutoff } | Select-Object -First 15
        if ($entries) { Write-Output ""; Write-Output "=== Stored Context ==="; $entries | ForEach-Object { Write-Output ("[" + $_.type + "] " + $_.content) }; Write-Output "=== end Stored Context ===" }
    } catch {}
}
"@ | Set-Content -Path $primePs1 -Encoding UTF8

    @"
$input = [Console]::In.ReadToEnd()
try { $transcript = ($input | ConvertFrom-Json).transcript_path } catch { $transcript = '' }
if ($transcript -and (Test-Path $transcript)) {
    try {
        $lines = Get-Content $transcript -Raw | ConvertFrom-Json -AsHashtable -ErrorAction SilentlyContinue
        if (-not $lines) { $lines = (Get-Content $transcript) | ForEach-Object { $_ | ConvertFrom-Json -ErrorAction SilentlyContinue } | Where-Object { $_ } }
        $last = ($lines | Where-Object { $_.type -eq 'assistant' }) | Select-Object -Last 1
        $chars = ([string]($last.message.content)).Length
        $out = [Math]::Max(1, [int]($chars / 4)); $in = $out * 4
        Invoke-RestMethod -Method Post -Uri 'http://localhost:8899/log' -ContentType 'application/json' -Body ("{`"input_tokens`":$in,`"output_tokens`":$out,`"model`":`"claude-sonnet-4-6`",`"description`":`"auto`",`"project`":`"$resolvedProject`"}") -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}
"@ | Set-Content -Path $stopPs1 -Encoding UTF8

    if (-not (Test-Path $settingsDir)) { New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null }
    $primeCmd = 'powershell -NoProfile -File "' + (To-ForwardSlashes $primePs1) + '"'
    $stopCmd = 'powershell -NoProfile -File "' + (To-ForwardSlashes $stopPs1) + '"'
    $hooks = @{
        hooks = @{
            SessionStart = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $primeCmd }) })
            PreCompact   = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $primeCmd }) })
            Stop         = @(@{ matcher = ""; hooks = @(@{ type = "command"; command = $stopCmd }) })
        }
    }
    $hooks | ConvertTo-Json -Depth 8 | Set-Content -Path $settingsFile -Encoding UTF8
    Write-Host "[$Tool] Context hooks ready (SessionStart + PreCompact + Stop)"

    Write-Host ""
    Write-Host "[$Tool] Questions, bugs, or feedback? Join the community:"
    Write-Host "[$Tool]    https://discord.gg/rxgVVgCh"
    Write-Host ""
    Write-Host "[$Tool] Starting claude..."
    Write-Host ""

    Push-Location $resolvedProject
    try {
        & claude
        $claudeExit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($claudeExit -ne 0) {
        Send-CliError "Running Claude" "Claude exited with code $claudeExit in dgc.ps1"
    }

    Write-Host ""
    Write-Host "[$Tool] Cleaning up..."
    if (Has-ClaudeMcp "dual-graph") {
        [void](Invoke-NativeQuiet "claude" @("mcp", "remove", "dual-graph"))
    }
    # Token counter is global; do not remove it on exit.
    if (Test-Path $pidFile) {
        try { Stop-Process -Id ([int](Get-Content $pidFile -Raw)) -Force -ErrorAction SilentlyContinue } catch {}
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
    if (Test-Path $portFile) {
        try {
            $killPort = [int](Get-Content $portFile -Raw)
            Get-NetTCPConnection -LocalPort $killPort -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object {
                Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
            }
        } catch {}
        Remove-Item $portFile -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[$Tool] Done."
    exit $claudeExit
} catch {
    $message = "$($_.Exception.Message)"
    if ($message) { Send-CliError "Launcher" $message }
    Write-Host "[$Tool] Error: $message" -ForegroundColor Red
    exit 1
}
