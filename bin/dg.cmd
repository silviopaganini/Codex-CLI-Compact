@echo off
:: dg — Codex CLI + dual-graph MCP launcher (Windows)
:: Usage: dg [project-path]

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
set "TOOL=dg"
set "R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev"
set "BASE_URL=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main"
set "NOTICE_FILE=%DG%\last_update_notice.txt"

:: ── Update check + one-time install hint per version ────────────────────────
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

:: ── Find a free port (8080-8099) ──────────────────────────────────────────
if defined DG_MCP_PORT (
    set "MCP_PORT=%DG_MCP_PORT%"
    goto :port_found
)
set "MCP_PORT=8080"
:find_port
netstat -an 2>nul | findstr /C:":%MCP_PORT% " | findstr "LISTENING" >nul 2>&1
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
echo [%TOOL%] Port    : %MCP_PORT%
echo.

:: ── Create data dir ────────────────────────────────────────────────────────
if not exist "%DATA_DIR%" mkdir "%DATA_DIR%"

:: ── Scan project ───────────────────────────────────────────────────────────
echo [%TOOL%] Scanning project...
"%PYTHON%" "%DG%\graph_builder.py" --root "%PROJECT%" --out "%DATA_DIR%\info_graph.json"
echo [%TOOL%] Scan complete.
echo.

:: ── Start MCP server in background ────────────────────────────────────────
echo [%TOOL%] Starting MCP server on port %MCP_PORT%...
set "LOG=%DATA_DIR%\mcp_server.log"
start /b "" cmd /c "set DG_DATA_DIR=%DATA_DIR%& set DUAL_GRAPH_PROJECT_ROOT=%PROJECT%& set DG_BASE_URL=http://localhost:%MCP_PORT%& set PORT=%MCP_PORT%& "%PYTHON%" "%DG%\mcp_graph_server.py" >> "%LOG%" 2>&1"

:: ── Wait for server to be ready ────────────────────────────────────────────
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
:: Save PID and port for cleanup
powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %MCP_PORT% -State Listen -EA 0).OwningProcess" > "%DATA_DIR%\mcp_server.pid" 2>nul
echo %MCP_PORT%> "%DATA_DIR%\mcp_port"
echo [%TOOL%] MCP server ready on port %MCP_PORT%.
echo.

:: ── Register MCP with Codex CLI ────────────────────────────────────────────
cmd /d /c "codex mcp remove dual-graph" >nul 2>&1
cmd /d /c "codex mcp add --transport http dual-graph http://localhost:%MCP_PORT%/mcp" >nul 2>&1 || cmd /d /c "codex mcp add dual-graph --url http://localhost:%MCP_PORT%/mcp"
echo [%TOOL%] MCP registered -> http://localhost:%MCP_PORT%/mcp
echo.

:: ── Launch Codex CLI ───────────────────────────────────────────────────────
echo [%TOOL%] Starting Codex CLI...
echo.
cd /d "%PROJECT%"
call codex

:: ── Cleanup after codex exits ──────────────────────────────────────────────
echo.
echo [%TOOL%] Cleaning up...
cmd /d /c "codex mcp remove dual-graph" >nul 2>&1
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
