@echo off
:: dgc — Claude Code + dual-graph MCP launcher (Windows)
:: Usage: dgc [project-path]

setlocal enabledelayedexpansion

set "DG=%USERPROFILE%\.dual-graph"
set "PYTHON=%DG%\venv\Scripts\python.exe"
set "TOOL=dgc"
set "POLICY_MARKER=dgc-policy-v9"
set "R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"

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
      echo [%TOOL%] Update available (%LOCAL_VER% ^→ %REMOTE_VER%) -- updating...
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/mcp_graph_server.py' -OutFile '%DG%\mcp_graph_server.py' -UseBasicParsing"
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/graph_builder.py' -OutFile '%DG%\graph_builder.py' -UseBasicParsing"
      powershell -NoProfile -Command "Invoke-WebRequest '%R2%/dual_graph_launch.sh' -OutFile '%DG%\dual_graph_launch.sh' -UseBasicParsing"
      echo %REMOTE_VER%> "%DG%\version.txt"
      echo [%TOOL%] Updated to %REMOTE_VER%.
    )
  )
)

:: ── Kill stale MCP server (by saved PID tree + by port) ────────────────────
if exist "%DATA_DIR%\mcp_server.pid" (
    set /p OLD_PID=<"%DATA_DIR%\mcp_server.pid"
    taskkill /PID !OLD_PID! /F /T >nul 2>&1
    del "%DATA_DIR%\mcp_server.pid" >nul 2>&1
)
if exist "%DATA_DIR%\mcp_port" (
    set /p OLD_PORT=<"%DATA_DIR%\mcp_port"
    for /f "tokens=5" %%q in ('netstat -ano 2^>nul ^| findstr /C:":%OLD_PORT% " ^| findstr "LISTENING"') do (
        taskkill /PID %%q /F /T >nul 2>&1
    )
)
del "%DATA_DIR%\mcp_server.log" >nul 2>&1
del "%DATA_DIR%\mcp_port" >nul 2>&1
timeout /t 2 /nobreak >nul

:: ── Find a free port (8080-8099) ───────────────────────────────────────────
if defined DG_MCP_PORT (
    set "MCP_PORT=%DG_MCP_PORT%"
    goto :port_found
)
set "MCP_PORT=8080"
:find_port
netstat -ano 2>nul | findstr /C:":%MCP_PORT% " | findstr "LISTENING" >nul 2>&1
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
        echo ^<^!-- %POLICY_MARKER% --^>
        echo # Dual-Graph Context Policy
        echo.
        echo This project uses a local dual-graph MCP server for efficient context retrieval.
        echo.
        echo ## MANDATORY: Always follow this order
        echo.
        echo 1. **Call `graph_continue` first** ^— before any file exploration, grep, or code reading.
        echo.
        echo 2. **If `graph_continue` returns `needs_project=true`**: call `graph_scan` with the
        echo    current project directory ^(`pwd`^). Do NOT ask the user.
        echo.
        echo 3. **If `graph_continue` returns `skip=true`**: project has fewer than 5 files.
        echo    Do NOT do broad or recursive exploration. Read only specific files if their names
        echo    are mentioned, or ask the user what to work on.
        echo.
        echo 4. **Read `recommended_files`** using `graph_read`.
        echo    - `recommended_files` may contain `file::symbol` entries ^(e.g. `src/auth.ts::handleLogin`^).
        echo      Pass them verbatim to `graph_read` ^— it reads only that symbol's lines, not the full file.
        echo.
        echo 5. **Check `confidence` and obey the caps strictly:**
        echo    - `confidence=high` -^> Stop. Do NOT grep or explore further.
        echo    - `confidence=medium` -^> If recommended files are insufficient, call `fallback_rg`
        echo      at most `max_supplementary_greps` time^(s^) with specific terms, then `graph_read`
        echo      at most `max_supplementary_files` additional file^(s^). Then stop.
        echo    - `confidence=low` -^> Call `fallback_rg` at most `max_supplementary_greps` time^(s^),
        echo      then `graph_read` at most `max_supplementary_files` file^(s^). Then stop.
        echo.
        echo ## Token Usage
        echo.
        echo A `token-counter` MCP is available for tracking live token usage.
        echo.
        echo - To check how many tokens a large file or text will cost **before** reading it:
        echo   `count_tokens^({text: "^<content^>"}^)`
        echo - To log actual usage after a task completes ^(if the user asks^):
        echo   `log_usage^({input_tokens: ^<est^>, output_tokens: ^<est^>, description: "^<task^>"}^)`
        echo - To show the user their running session cost:
        echo   `get_session_stats^(^)`
        echo.
        echo ## Rules
        echo.
        echo - Do NOT use `rg`, `grep`, or bash file exploration before calling `graph_continue`.
        echo - Do NOT do broad/recursive exploration at any confidence level.
        echo - `max_supplementary_greps` and `max_supplementary_files` are hard caps - never exceed them.
        echo - Do NOT dump full chat history.
        echo - Do NOT call `graph_retrieve` more than once per turn.
        echo - After edits, call `graph_register_edit` with the changed files. Use `file::symbol` notation ^(e.g. `src/auth.ts::handleLogin`^) when the edit targets a specific function, class, or hook.
    ) > "%DOC_FILE%"
    echo [%TOOL%] CLAUDE.md written.
) else (
    echo [%TOOL%] CLAUDE.md already up to date, skipping.
)

:: ── Scan project ───────────────────────────────────────────────────────────
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"
echo [%TOOL%] Scanning project...
"%PYTHON%" "%DG%\graph_builder.py" --root "%PROJECT%" --out "%DATA_DIR%\info_graph.json"
echo [%TOOL%] Scan complete.
echo.

:: ── Start MCP server in background ──────────────────────────────���─────────
echo [%TOOL%] Starting MCP server on port %MCP_PORT%...
set "LOG=%DATA_DIR%\mcp_server.log"
start /b "" cmd /c "set DG_DATA_DIR=%DATA_DIR%& set DUAL_GRAPH_PROJECT_ROOT=%PROJECT%& set DG_BASE_URL=http://localhost:%MCP_PORT%& set PORT=%MCP_PORT%& "%PYTHON%" "%DG%\mcp_graph_server.py" > "%LOG%" 2>&1"

:: Wait for server to be ready (up to 20s)
set /a TRIES=0
:wait_loop
set /a TRIES+=1
if !TRIES! gtr 20 (
    echo [%TOOL%] Error: MCP server did not start. Check %LOG%
    exit /b 1
)
powershell -NoProfile -Command "try { $null = (New-Object Net.Sockets.TcpClient).Connect('localhost',%MCP_PORT%); exit 0 } catch { exit 1 }" >nul 2>&1
if %errorlevel% neq 0 (
    timeout /t 1 /nobreak >nul
    goto :wait_loop
)

:: Save PID of the process listening on our port (for cleanup on next run)
for /f "tokens=5" %%p in ('netstat -ano 2^>nul ^| findstr /C:":%MCP_PORT% " ^| findstr "LISTENING"') do (
    echo %%p> "%DATA_DIR%\mcp_server.pid"
    goto :pid_saved
)
:pid_saved

:: Save port for hooks
echo %MCP_PORT%> "%DATA_DIR%\mcp_port"
echo [%TOOL%] MCP server ready on port %MCP_PORT%.
echo.

:: ── Register dual-graph MCP ────────────────────────────────────────────────
claude mcp remove dual-graph >nul 2>&1
claude mcp add --transport http dual-graph "http://localhost:%MCP_PORT%/mcp" >nul 2>&1
echo [%TOOL%] MCP config updated -^> http://localhost:%MCP_PORT%/mcp

:: ── Register token-counter MCP via npx ────────────────────────────────────
claude mcp remove token-counter >nul 2>&1
claude mcp add token-counter -- npx -y token-counter-mcp >nul 2>&1
echo [%TOOL%] Token counter -^> npx token-counter-mcp

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
) > "%PRIME_PS1%"

if not exist "%SETTINGS_DIR%" mkdir "%SETTINGS_DIR%"
(
    echo {
    echo   "hooks": {
    echo     "SessionStart": [
    echo       {"matcher": "", "hooks": [{"type": "command", "command": "powershell -NoProfile -File \"%PRIME_PS1%\""}]}
    echo     ],
    echo     "PreCompact": [
    echo       {"matcher": "", "hooks": [{"type": "command", "command": "powershell -NoProfile -File \"%PRIME_PS1%\""}]}
    echo     ]
    echo   }
    echo }
) > "%SETTINGS_FILE%"
echo [%TOOL%] Context hooks ready ^(SessionStart + PreCompact^)

:: ── Launch Claude (via sub-batch so Ctrl+C cleanup still runs) ────────────
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

:: ── Cleanup after claude exits (runs even after Ctrl+C -> Y) ──────────────
echo.
echo [%TOOL%] Cleaning up...
claude mcp remove dual-graph >nul 2>&1
claude mcp remove token-counter >nul 2>&1
if exist "%DATA_DIR%\mcp_server.pid" (
    set /p KILL_PID=<"%DATA_DIR%\mcp_server.pid"
    taskkill /PID !KILL_PID! /F /T >nul 2>&1
    del "%DATA_DIR%\mcp_server.pid" >nul 2>&1
)
if exist "%DATA_DIR%\mcp_port" (
    set /p KILL_PORT=<"%DATA_DIR%\mcp_port"
    for /f "tokens=5" %%q in ('netstat -ano 2^>nul ^| findstr /C:":%KILL_PORT% " ^| findstr "LISTENING"') do (
        taskkill /PID %%q /F /T >nul 2>&1
    )
)
del "%DATA_DIR%\mcp_port" >nul 2>&1
echo [%TOOL%] Done.
