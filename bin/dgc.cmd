@echo off
:: dgc — Claude Code + dual-graph MCP launcher (Windows)
:: Usage: dgc [project-path]

setlocal enabledelayedexpansion

set "DG=%USERPROFILE%\.dual-graph"
set "PYTHON=%DG%\venv\Scripts\python.exe"
set "TOOL=dgc"

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
echo [%TOOL%] MCP server ready on port %MCP_PORT%.
echo.

:: ── Register MCP with Claude Code ─────────────────────────────────────────
claude mcp remove dual-graph >nul 2>&1
claude mcp add --transport http dual-graph "http://localhost:%MCP_PORT%/mcp"
echo [%TOOL%] MCP registered -> http://localhost:%MCP_PORT%/mcp
echo.

:: ── Launch Claude Code ─────────────────────────────────────────────────────
echo [%TOOL%] Starting Claude Code...
echo.
cd /d "%PROJECT%"
claude
