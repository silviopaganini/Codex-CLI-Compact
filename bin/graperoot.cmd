@echo off
:: graperoot — Windows bootstrap for Dual-Graph with AI tool selection
:: Usage:
::   graperoot [path] --claude    Claude Code  (same as dgc)
::   graperoot [path] --codex     OpenAI Codex (same as dg)
::   graperoot [path] --cursor    Cursor IDE
::   graperoot [path] --gemini    Google Gemini CLI
::
:: Default tool: --claude.  Default path: current directory.

setlocal EnableDelayedExpansion

set "DG=%USERPROFILE%\.dual-graph"
set "BOOTSTRAP_PS1=%TEMP%\dual_graph_graperoot_bootstrap.ps1"
set "REMOTE_GRAPEROOT_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/graperoot.ps1"
set "REMOTE_DGC_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dgc.ps1"
set "REMOTE_DG_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dg.ps1"

if not exist "%DG%" mkdir "%DG%" >nul 2>&1

:: ── Parse assistant flag from args ───────────────────────────────────────────
set "ASSISTANT=claude"
set "PASSTHROUGH="
set "FOUND_PATH="

for %%A in (%*) do (
  if /i "%%A"=="--claude"  set "ASSISTANT=claude"
  if /i "%%A"=="claude"    set "ASSISTANT=claude"
  if /i "%%A"=="--codex"   set "ASSISTANT=codex"
  if /i "%%A"=="codex"     set "ASSISTANT=codex"
  if /i "%%A"=="--cursor"  set "ASSISTANT=cursor"
  if /i "%%A"=="cursor"    set "ASSISTANT=cursor"
  if /i "%%A"=="--gemini"  set "ASSISTANT=gemini"
  if /i "%%A"=="gemini"    set "ASSISTANT=gemini"
)

:: ── Delegate to existing launchers for claude / codex ────────────────────────
if /i "%ASSISTANT%"=="claude" (
  set "LOCAL_PS1=%DG%\dgc.ps1"
  set "REMOTE_PS1=%REMOTE_DGC_PS1%"
  goto :run_ps1
)
if /i "%ASSISTANT%"=="codex" (
  set "LOCAL_PS1=%DG%\dg.ps1"
  set "REMOTE_PS1=%REMOTE_DG_PS1%"
  goto :run_ps1
)

:: ── For cursor / gemini: use graperoot.ps1 ───────────────────────────────────
set "LOCAL_PS1=%DG%\graperoot.ps1"
set "REMOTE_PS1=%REMOTE_GRAPEROOT_PS1%"

:run_ps1
:: Download latest ps1 (best-effort; falls back to cached local copy)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest '%REMOTE_PS1%' -OutFile '%LOCAL_PS1%' -UseBasicParsing -TimeoutSec 10 | Out-Null } catch {}" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { Invoke-WebRequest '%REMOTE_PS1%' -OutFile '%BOOTSTRAP_PS1%' -UseBasicParsing -TimeoutSec 10 | Out-Null } catch {}" >nul 2>&1

if exist "%BOOTSTRAP_PS1%" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%BOOTSTRAP_PS1%" %*
  set "EXIT_CODE=%ERRORLEVEL%"
  del "%BOOTSTRAP_PS1%" >nul 2>&1
  exit /b %EXIT_CODE%
)

if exist "%LOCAL_PS1%" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%LOCAL_PS1%" %*
  exit /b %ERRORLEVEL%
)

echo [graperoot] Error: could not download launcher script.
echo [graperoot] Reinstall with:
echo [graperoot]   irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 ^| iex
exit /b 1
