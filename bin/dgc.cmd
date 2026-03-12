@echo off
:: dgc — Claude Code + dual-graph MCP launcher (Windows)
:: Usage: dgc [project-path]

setlocal enabledelayedexpansion

set "DG=%USERPROFILE%\.dual-graph"

:: ── Apply pending self-update (downloaded by previous run) ────────────────
if exist "%DG%\dgc.cmd.new" (
    move /y "%DG%\dgc.cmd.new" "%~f0" >nul 2>&1
    if not errorlevel 1 (
        call "%~f0" %*
        exit /b
    )
)
set "PYTHON=%DG%\venv\Scripts\python.exe"
set "TOOL=dgc"
set "POLICY_MARKER=dgc-policy-v10"
set "R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
set "BASE_URL=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
set "NOTICE_FILE=%DG%\last_update_notice.txt"
set "WEBHOOK_URL=https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec"

:: ── Detect install method (Scoop vs direct) ───────────────────────────────
set "REINSTALL_CMD=irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 | iex"
if defined SCOOP (
    if exist "%SCOOP%\shims\dgc.cmd" set "REINSTALL_CMD=scoop update dual-graph"
) else (
    if exist "%USERPROFILE%\scoop\shims\dgc.cmd" set "REINSTALL_CMD=scoop update dual-graph"
)

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
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/mcp_graph_server.py' -OutFile '%DG%\mcp_graph_server.py' -UseBasicParsing" >nul 2>&1
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/graph_builder.py' -OutFile '%DG%\graph_builder.py' -UseBasicParsing" >nul 2>&1
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/dual_graph_launch.sh' -OutFile '%DG%\dual_graph_launch.sh' -UseBasicParsing" >nul 2>&1
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
    powershell -NoProfile -Command "try { (Invoke-WebRequest '%R2%/CLAUDE.md.template' -UseBasicParsing).Content | Set-Content -LiteralPath '%DOC_FILE%' -Encoding UTF8; exit 0 } catch { exit 1 }" >nul 2>&1
    if errorlevel 1 (
        echo [%TOOL%] Warning: could not fetch CLAUDE.md template. Check your connection.
    ) else (
        echo [%TOOL%] CLAUDE.md written.
    )
) else (
    echo [%TOOL%] CLAUDE.md already up to date, skipping.
)

:: ── Scan project ───────────────────────────────────────────────────────────
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
if not exist "%DATA_DIR%\context-store.json" echo []> "%DATA_DIR%\context-store.json"
echo [%TOOL%] Scanning project...
"%PYTHON%" "%DG%\graph_builder.py" --root "%PROJECT%" --out "%DATA_DIR%\info_graph.json"
if errorlevel 1 (
    echo [%TOOL%] Error: project scan failed.
    
    :: Attempt to send error telemetry
    powershell -NoProfile -Command "try { $id='%COMPUTERNAME%'; $f='%DG%\identity.json'; if (Test-Path $f) { $mid=(Get-Content $f -Raw | ConvertFrom-Json).machine_id; if ($mid) { $id=$mid } }; Invoke-RestMethod -Method Post -Uri 'https://script.google.com/macros/s/AKfycbyq_5igbBUORhSqMNktAoX2GQg8BadKcYZOTV-XRUr3vbY3QuK7jjS8EWLg_pZyMDuD/exec' -ContentType 'application/json' -Body ('{\"type\":\"cli_error\",\"platform\":\"windows\",\"machine_id\":\"'+$id+'\",\"error_message\":\"Project scan failed in dgc.cmd\",\"script_step\":\"Scanning project\"}') -EA 0 -TimeoutSec 5 | Out-Null } catch {}" >nul 2>&1
    
    echo [%TOOL%] If this keeps happening, reinstall with:
    echo [%TOOL%]   %REINSTALL_CMD%
    exit /b 1
)
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
    powershell -NoProfile -Command "try { $id='%COMPUTERNAME%'; $f='%DG%\identity.json'; if (Test-Path $f) { $mid=(Get-Content $f -Raw | ConvertFrom-Json).machine_id; if ($mid) { $id=$mid } }; Invoke-RestMethod -Method Post -Uri '%WEBHOOK_URL%' -ContentType 'application/json' -Body ('{\"type\":\"cli_error\",\"platform\":\"windows\",\"machine_id\":\"'+$id+'\",\"error_message\":\"MCP server did not start in dgc.cmd\",\"script_step\":\"Starting MCP server\"}') -EA 0 -TimeoutSec 5 | Out-Null } catch {}" >nul 2>&1
    echo [%TOOL%] If this keeps happening, reinstall with:
    echo [%TOOL%]   %REINSTALL_CMD%
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
if errorlevel 1 (
    echo [%TOOL%] Error: failed to register MCP in Claude.
    powershell -NoProfile -Command "try { $id='%COMPUTERNAME%'; $f='%DG%\identity.json'; if (Test-Path $f) { $mid=(Get-Content $f -Raw | ConvertFrom-Json).machine_id; if ($mid) { $id=$mid } }; Invoke-RestMethod -Method Post -Uri '%WEBHOOK_URL%' -ContentType 'application/json' -Body ('{\"type\":\"cli_error\",\"platform\":\"windows\",\"machine_id\":\"'+$id+'\",\"error_message\":\"MCP registration failed in dgc.cmd\",\"script_step\":\"Registering MCP\"}') -EA 0 -TimeoutSec 5 | Out-Null } catch {}" >nul 2>&1
    echo [%TOOL%] If this keeps happening, reinstall with:
    echo [%TOOL%]   %REINSTALL_CMD%
    exit /b 1
)
echo [%TOOL%] MCP registered -^> http://localhost:%MCP_PORT%/mcp
cmd /d /c "claude mcp remove token-counter --scope user" >nul 2>&1
cmd /d /c "claude mcp remove token-counter" >nul 2>&1
cmd /d /c "claude mcp add --scope user token-counter -- npx -y token-counter-mcp" >nul 2>&1
echo [%TOOL%] Token counter registered (global)

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

set "STOP_PS1=%DATA_DIR%\stop_hook.ps1"
(
    echo $input = [Console]::In.ReadToEnd^(^)
    echo try { $transcript = ^($input ^| ConvertFrom-Json^).transcript_path } catch { $transcript = '' }
    echo if ^($transcript -and ^(Test-Path $transcript^)^) {
    echo     try {
    echo         $lines = Get-Content $transcript -Raw ^| ConvertFrom-Json -AsHashtable -EA 0
    echo         if ^(-not $lines^) { $lines = ^(Get-Content $transcript^) ^| ForEach-Object { $_ ^| ConvertFrom-Json -EA 0 } ^| Where-Object { $_ } }
    echo         $last = ^($lines ^| Where-Object { $_.type -eq 'assistant' }^) ^| Select-Object -Last 1
    echo         $chars = ^([string]^($last.message.content^)^).Length
    echo         $out = [math]::Max^(1, [int]^($chars / 4^)^); $in = $out * 4
    echo         Invoke-RestMethod -Method Post -Uri 'http://localhost:8899/log' -ContentType 'application/json' -Body ^("{`"input_tokens`":$in,`"output_tokens`":$out,`"model`":`"claude-sonnet-4-6`",`"description`":`"auto`",`"project`":`"%PROJECT%`"}"^) -EA 0 ^| Out-Null
    echo     } catch {}
    echo }
) > "%STOP_PS1%"

if not exist "%SETTINGS_DIR%" mkdir "%SETTINGS_DIR%"
powershell -NoProfile -Command ^
  "& { $prime = 'powershell -NoProfile -File ""%PRIME_PS1%""'; $stop = 'powershell -NoProfile -File ""%STOP_PS1%""'; $obj = @{ hooks = @{ SessionStart = @(@{ matcher = ''; hooks = @(@{ type = 'command'; command = $prime }) }); PreCompact = @(@{ matcher = ''; hooks = @(@{ type = 'command'; command = $prime }) }); Stop = @(@{ matcher = ''; hooks = @(@{ type = 'command'; command = $stop }) }) } }; $obj | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath '%SETTINGS_FILE%' -Encoding UTF8 }"
echo [%TOOL%] Context hooks ready ^(SessionStart + PreCompact + Stop^)

:: ── One-time feedback form ─────────────────────────────────────────────────
if not exist "%DG%\feedback_done" (
    set "SHOW_FEEDBACK=1"
    if exist "%DG%\install_date.txt" (
        set /p INSTALL_DATE=<"%DG%\install_date.txt"
        powershell -NoProfile -Command "if ((Get-Date -Format 'yyyy-MM-dd') -gt '%INSTALL_DATE%') { exit 0 } else { exit 1 }" >nul 2>&1
        if errorlevel 1 set "SHOW_FEEDBACK=0"
    )
    if "!SHOW_FEEDBACK!"=="1" (
        echo ====================================================
        echo   One quick question before we start ^(asked once only^)
        echo ====================================================
        set /p FB_RATING="  How useful has Graperoot been so far? (1-5): "
        set /p FB_IMPROVE="  Anything you'd improve? (press Enter to skip): "
        powershell -NoProfile -Command ^
          "try { $id='%COMPUTERNAME%'; $f='%DG%\identity.json'; if (Test-Path $f) { $mid=(Get-Content $f -Raw | ConvertFrom-Json).machine_id; if ($mid) { $id=$mid } }; Invoke-RestMethod -Method Post -Uri 'https://script.google.com/macros/s/AKfycbzsOnvAiDTdhDaW73ErztJztPqT25WOCFn29VzrRYZRhBUIwHRu677DoATctAEiq6dp4Q/exec' -ContentType 'application/json' -Body ('{\"rating\":\"!FB_RATING!\",\"improve\":\"!FB_IMPROVE!\",\"machine_id\":\"'+$id+'\"}') -EA 0 | Out-Null } catch {}" >nul 2>&1
        echo. > "%DG%\feedback_done"
        echo   Thanks^! You won't see this again.
        echo ====================================================
        echo.
    )
)

:: ── Launch Claude (sub-batch so cleanup runs after Ctrl+C) ────────────────
echo.
echo [%TOOL%] 💬 Questions, bugs, or feedback? Join the community:
echo [%TOOL%]    https://discord.gg/rxgVVgCh
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
