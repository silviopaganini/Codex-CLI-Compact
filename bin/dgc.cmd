@echo off
:: dgc — Claude Code + dual-graph MCP launcher (Windows)
:: Usage: dgc [project-path]

setlocal enabledelayedexpansion

:: ── Apply pending self-update (downloaded by previous run) ────────────────
if exist "%~f0.new" (
    move /y "%~f0.new" "%~f0" >nul 2>&1
    if not errorlevel 1 (
        call "%~f0" %*
        exit /b
    )
)

set "DG=%USERPROFILE%\.dual-graph"
set "PYTHON=%DG%\venv\Scripts\python.exe"
set "TOOL=dgc"
set "POLICY_MARKER=dgc-policy-v10"
set "R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
set "BASE_URL=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
set "NOTICE_FILE=%DG%\last_update_notice.txt"

if "%~1"=="" (
    set "PROJECT=%CD%"
) else (
    set "PROJECT=%~1"
)

if not exist "%PROJECT%" (
    echo [%TOOL%] Error: path not found: %PROJECT%
    exit /b 1
)

set "DATA_DIR=%PROJECT%\.dual-graph"
set "DOC_FILE=%PROJECT%\CLAUDE.md"

:: ── Self-update from R2 ────────────────────────────────────────────────────
set "LOCAL_VER=0"
if exist "%DG%\version.txt" set /p LOCAL_VER=<"%DG%\version.txt"
powershell -NoProfile -Command ^
  "try { $v=(Invoke-WebRequest '%R2%/version.txt' -UseBasicParsing -TimeoutSec 3).Content.Trim(); Write-Output $v } catch { Write-Output '' }" ^
  > "%TEMP%\dg_remote_ver.txt" 2>nul
set /p REMOTE_VER=<"%TEMP%\dg_remote_ver.txt"

if defined REMOTE_VER (
  if not "%REMOTE_VER%"=="" (
    if not "%REMOTE_VER%"=="%LOCAL_VER%" (
      set "LAST_NOTICE_VER="
      if exist "%NOTICE_FILE%" set /p LAST_NOTICE_VER=<"%NOTICE_FILE%"
      if not "%LAST_NOTICE_VER%"=="%REMOTE_VER%" (
        echo [%TOOL%] New version available: %LOCAL_VER% -^> %REMOTE_VER%
        echo [%TOOL%] To refresh launcher files run:
        echo [%TOOL%]   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 ^| iex
        echo %REMOTE_VER%> "%NOTICE_FILE%"
      )
      echo [%TOOL%] Update available: %LOCAL_VER% -^> %REMOTE_VER% ... updating
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/mcp_graph_server.py' -OutFile '%DG%\mcp_graph_server.py' -UseBasicParsing"
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/graph_builder.py' -OutFile '%DG%\graph_builder.py' -UseBasicParsing"
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/dual_graph_launch.sh' -OutFile '%DG%\dual_graph_launch.sh' -UseBasicParsing"
      powershell -NoProfile -Command "try { Invoke-WebRequest '%BASE_URL%/bin/dgc.cmd' -OutFile '%DG%\dgc.cmd.new' -UseBasicParsing } catch {}" >nul 2>&1
      powershell -NoProfile -Command "try { Invoke-WebRequest '%BASE_URL%/bin/dg.cmd' -OutFile '%DG%\dg.cmd.new' -UseBasicParsing } catch {}" >nul 2>&1
      powershell -NoProfile -Command "try { Invoke-WebRequest '%BASE_URL%/bin/dgc.ps1' -OutFile '%DG%\dgc.ps1' -UseBasicParsing } catch {}" >nul 2>&1
      powershell -NoProfile -Command "try { Invoke-WebRequest '%BASE_URL%/bin/dg.ps1' -OutFile '%DG%\dg.ps1' -UseBasicParsing } catch {}" >nul 2>&1
      echo %REMOTE_VER%> "%DG%\version.txt"
      echo [%TOOL%] Updated to %REMOTE_VER%. Launcher will refresh on next run.
    )
  )
)

:: ── Kill stale MCP server ──────────────────────────────────────────────────
if exist "%DATA_DIR%\mcp_server.pid" (
    set /p OLD_PID=<"%DATA_DIR%\mcp_server.pid"
    taskkill /PID !OLD_PID! /F /T >nul 2>&1
    del "%DATA_DIR%\mcp_server.pid" >nul 2>&1
    timeout /t 2 /nobreak >nul
)
if exist "%DATA_DIR%\mcp_port" (
    set /p OLD_PORT=<"%DATA_DIR%\mcp_port"
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort !OLD_PORT! -State Listen -EA 0 | Select-Object -Expand OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -EA 0 }" >nul 2>&1
    del "%DATA_DIR%\mcp_port" >nul 2>&1
)
del "%DATA_DIR%\mcp_server.log" >nul 2>&1

:: ── Find a free port (8080-8099) ───────────────────────────────────────────
if defined DG_MCP_PORT (
    set "MCP_PORT=%DG_MCP_PORT%"
    goto :port_found
)
set "MCP_PORT=8080"
:find_port
netstat -an 2>nul | findstr ":%MCP_PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    set /a MCP_PORT+=1
    if !MCP_PORT! gtr 8099 (
        echo [%TOOL%] Error: no free port in range 8080-8099
        exit /b 1
    )
    goto :find_port
)
:port_found

echo [%TOOL%] Project : %PROJECT%
echo [%TOOL%] Data    : %DATA_DIR%
echo.

:: ── Ensure .gitignore has .dual-graph/ ────────────────────────────────────
if exist "%PROJECT%\.gitignore" (
    findstr /C:".dual-graph/" "%PROJECT%\.gitignore" >nul 2>&1
    if errorlevel 1 (
        echo .dual-graph/>> "%PROJECT%\.gitignore"
        echo [%TOOL%] Added .dual-graph/ to .gitignore
    )
)

:: ── Write CLAUDE.md policy (create or upgrade) ────────────────────────────
set "NEED_WRITE=0"
if not exist "%DOC_FILE%" set "NEED_WRITE=1"
if exist "%DOC_FILE%" (
    findstr /C:"graph_continue" "%DOC_FILE%" >nul 2>&1
    if not errorlevel 1 (
        findstr /C:"%POLICY_MARKER%" "%DOC_FILE%" >nul 2>&1
        if errorlevel 1 set "NEED_WRITE=1"
    )
)

if "%NEED_WRITE%"=="1" (
    echo [%TOOL%] Writing CLAUDE.md policy...
    (
        echo ^<!-- %POLICY_MARKER% --^>
        echo # Dual-Graph Context Policy
        echo.
        echo This project uses a local dual-graph MCP server for efficient context retrieval.
        echo.
        echo ## MANDATORY: Always follow this order
        echo.
        echo 1. Call graph_continue first - before any file exploration, grep, or code reading.
        echo 2. If needs_project=true: call graph_scan with the project directory.
        echo 3. If skip=true: project has fewer than 5 files. Read only specific files asked about.
        echo 4. Read recommended_files using graph_read.
        echo 5. Obey confidence caps: high=stop, medium/low=limited fallback_rg then stop.
        echo.
        echo ## Token Usage
        echo A token-counter MCP is available. Use count_tokens before reading large files.
        echo Use get_session_stats to show running cost.
        echo.
        echo ## Rules
        echo - Do NOT use rg/grep/bash exploration before graph_continue.
        echo - Do NOT do broad/recursive exploration at any confidence level.
        echo - Do NOT call graph_retrieve more than once per turn.
        echo - After edits, call graph_register_edit with changed files.
        echo.
        echo ## Context Store
        echo Append to .dual-graph\context-store.json when you make a decision, task, next step, fact, or blocker.
        echo Format: {"type":"decision^|task^|next^|fact^|blocker","content":"max 15 words","tags":[],"files":[],"date":"YYYY-MM-DD"}
        echo To append: Read file, add entry to array, Write back, call graph_register_edit on .dual-graph/context-store.json.
        echo Only log things worth remembering across sessions. Log immediately, not at session end.
        echo.
        echo ## Session End
        echo When user signals done (bye/done/wrap up), update CONTEXT.md: Current Task, Key Decisions (max 3^), Next Steps (max 3^).
        echo Keep CONTEXT.md under 20 lines. Only what is needed to resume next session.
    ) > "%DOC_FILE%"
    echo [%TOOL%] CLAUDE.md written.
) else (
    echo [%TOOL%] CLAUDE.md already up to date, skipping.
)

:: ── Scan project ───────────────────────────────────────────────────────────
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%DATA_DIR%\context-store.json" echo []> "%DATA_DIR%\context-store.json"
echo [%TOOL%] Scanning project...
"%PYTHON%" "%DG%\graph_builder.py" --root "%PROJECT%" --out "%DATA_DIR%\info_graph.json"
echo [%TOOL%] Scan complete.
echo.

:: ── Start MCP server via temp bat (clean quoting) ─────────────────────────
echo [%TOOL%] Starting MCP server on port %MCP_PORT%...
set "LOG=%DATA_DIR%\mcp_server.log"
set "SRV_BAT=%DATA_DIR%\start_server.bat"
(
    echo @echo off
    echo set DG_DATA_DIR=%DATA_DIR%
    echo set DUAL_GRAPH_PROJECT_ROOT=%PROJECT%
    echo set DG_BASE_URL=http://localhost:%MCP_PORT%
    echo set PORT=%MCP_PORT%
    echo "%PYTHON%" "%DG%\mcp_graph_server.py" ^>"%LOG%" 2^>^&1
) > "%SRV_BAT%"
start /b "" cmd /c "%SRV_BAT%"

:: Wait for server ready (up to 20s)
set /a TRIES=0
:wait_loop
set /a TRIES+=1
if !TRIES! gtr 20 (
    echo [%TOOL%] Error: MCP server did not start. Check %LOG%
    exit /b 1
)
powershell -NoProfile -Command "try{$null=(New-Object Net.Sockets.TcpClient).Connect('localhost',%MCP_PORT%);exit 0}catch{exit 1}" >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 1 /nobreak >nul
    goto :wait_loop
)

:: Save PID and port for cleanup
powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %MCP_PORT% -State Listen -EA 0).OwningProcess" > "%DATA_DIR%\mcp_server.pid" 2>nul
echo %MCP_PORT%> "%DATA_DIR%\mcp_port"
echo [%TOOL%] MCP server ready on port %MCP_PORT%.
echo.

:: ── Register MCPs ──────────────────────────────────────────────────────────
cmd /d /c "claude mcp remove dual-graph" >nul 2>&1
cmd /d /c "claude mcp add --transport http dual-graph http://localhost:%MCP_PORT%/mcp" >nul 2>&1
echo [%TOOL%] MCP registered -^> http://localhost:%MCP_PORT%/mcp
cmd /d /c "claude mcp remove token-counter" >nul 2>&1
cmd /d /c "claude mcp add token-counter -- npx -y token-counter-mcp" >nul 2>&1
echo [%TOOL%] Token counter registered

:: ── Context hooks (SessionStart + PreCompact) ─────────────────────────────
set "PRIME_PS1=%DATA_DIR%\prime.ps1"
set "SETTINGS_DIR=%PROJECT%\.claude"
set "SETTINGS_FILE=%SETTINGS_DIR%\settings.local.json"

(
    echo $port = if ^(Test-Path '%DATA_DIR%\mcp_port'^) { Get-Content '%DATA_DIR%\mcp_port' } else { '%MCP_PORT%' }
    echo try {
    echo     $out = ^(Invoke-WebRequest "http://localhost:$port/prime" -UseBasicParsing -TimeoutSec 3^).Content
    echo     if ^($out^) { Write-Output $out; Write-Error "[dual-graph] Context loaded ^(port $port^)" }
    echo } catch {
    echo     Write-Error "[dual-graph] MCP server not reachable on port $port -- run dgc to restart"
    echo }
    echo $ctxFile = '%PROJECT%\CONTEXT.md'
    echo if ^(Test-Path $ctxFile^) { Write-Output ""; Write-Output "=== CONTEXT.md ==="; Get-Content $ctxFile -Raw; Write-Output "=== end CONTEXT.md ===" }
    echo $storeFile = '%DATA_DIR%\context-store.json'
    echo if ^(Test-Path $storeFile^) {
    echo     $cutoff = ^(Get-Date^).AddDays^(-7^).ToString^('yyyy-MM-dd'^)
    echo     try {
    echo         $entries = ^(Get-Content $storeFile -Raw ^| ConvertFrom-Json^) ^| Where-Object { $_.date -ge $cutoff } ^| Select-Object -First 15
    echo         if ^($entries^) { Write-Output ""; Write-Output "=== Stored Context ==="; $entries ^| ForEach-Object { Write-Output ^("[" + $_.type + "] " + $_.content^) }; Write-Output "=== end Stored Context ===" }
    echo     } catch {}
    echo }
) > "%PRIME_PS1%"

if not exist "%SETTINGS_DIR%" mkdir "%SETTINGS_DIR%"
powershell -NoProfile -Command ^
  "& { $cmd = 'powershell -NoProfile -File ""%PRIME_PS1%""'; $obj = @{ hooks = @{ SessionStart = @(@{ matcher = ''; hooks = @(@{ type = 'command'; command = $cmd }) }); PreCompact = @(@{ matcher = ''; hooks = @(@{ type = 'command'; command = $cmd }) }) } }; $obj | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath '%SETTINGS_FILE%' -Encoding UTF8 }"
echo [%TOOL%] Context hooks ready ^(SessionStart + PreCompact^)

:: ── Launch Claude (sub-batch so cleanup runs after Ctrl+C) ────────────────
echo.
echo [%TOOL%] Starting claude...
echo.
set "RUN_BAT=%TEMP%\dgc_run_%RANDOM%.bat"
(
    echo @echo off
    echo cd /d "%PROJECT%"
    echo claude
) > "%RUN_BAT%"
call "%RUN_BAT%"
del "%RUN_BAT%" >nul 2>&1

:: ── Cleanup after claude exits ─────────────────────────────────────────────
echo.
echo [%TOOL%] Cleaning up...
cmd /d /c "claude mcp remove dual-graph" >nul 2>&1
cmd /d /c "claude mcp remove token-counter" >nul 2>&1
if exist "%DATA_DIR%\mcp_server.pid" (
    set /p KILL_PID=<"%DATA_DIR%\mcp_server.pid"
    taskkill /PID !KILL_PID! /F /T >nul 2>&1
    del "%DATA_DIR%\mcp_server.pid" >nul 2>&1
)
if exist "%DATA_DIR%\mcp_port" (
    set /p KILL_PORT=<"%DATA_DIR%\mcp_port"
    powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort !KILL_PORT! -State Listen -EA 0 | Select-Object -Expand OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force -EA 0 }" >nul 2>&1
    del "%DATA_DIR%\mcp_port" >nul 2>&1
)
echo [%TOOL%] Done.
