@echo off
:: graperoot — Windows bootstrap for Dual-Graph with AI tool selection
:: Usage:
::   graperoot [path] --claude    Claude Code  (same as dgc)
::   graperoot [path] --codex     OpenAI Codex (same as dg)
::   graperoot [path] --cursor    Cursor IDE
::   graperoot [path] --gemini    Google Gemini CLI
::   graperoot [path] --opencode  OpenCode
::   graperoot [path] --copilot   GitHub Copilot (VS Code)
::
:: Default tool: --claude.  Default path: current directory.

setlocal EnableDelayedExpansion

set "DG=%USERPROFILE%\.dual-graph"
set "LOCAL_PS1=%DG%\graperoot.ps1"
set "BOOTSTRAP_PS1=%TEMP%\dual_graph_graperoot_bootstrap.ps1"
set "REMOTE_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/graperoot.ps1"
set "REMOTE_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/graperoot.ps1"
set "REMOTE_DGC_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dgc.ps1"
set "REMOTE_DGC_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dgc.ps1"
set "REMOTE_DG_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dg.ps1"
set "REMOTE_DG_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dg.ps1"
set "REMOTE_DGC_CMD_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dgc.cmd"
set "REMOTE_DG_CMD_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dg.cmd"
set "INSTALL_METHOD=direct"
set "REPAIR_CMD=irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 ^| iex"

if not exist "%DG%" mkdir "%DG%" >nul 2>&1

if defined SCOOP (
  if exist "%SCOOP%\shims\graperoot.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
) else (
  if exist "%USERPROFILE%\scoop\shims\graperoot.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
)

:: Bootstrap: R2-first atomic download (dl), GitHub fallback with UTF8 parse check (dls).
:: R2 is a direct object store — no CDN cache — so no ScriptBlock parse check needed.
:: GitHub raw CDN can serve stale UTF-8 content that PS5.1 misreads as Windows-1252,
:: so dls uses -Encoding UTF8 before accepting the file.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$gh='%REMOTE_PS1%';$r2='%REMOTE_PS1_R2%';$loc='%LOCAL_PS1%';$bs='%BOOTSTRAP_PS1%';" ^
  "function dl($u,$o){$t=$o+'.tmp';try{Invoke-WebRequest $u -OutFile $t -UseBasicParsing -TimeoutSec 15;if((Test-Path $t)-and(Get-Item $t).Length-gt 1024){Move-Item $t $o -Force;return $true}}catch{};Remove-Item $t -Force -EA SilentlyContinue;return $false};" ^
  "function dls($u,$o){$t=$o+'.tmp';try{Invoke-WebRequest $u -OutFile $t -UseBasicParsing -TimeoutSec 15;if((Test-Path $t)-and(Get-Item $t).Length-gt 1024){try{[void][System.Management.Automation.ScriptBlock]::Create((Get-Content $t -Raw -Encoding UTF8));Move-Item $t $o -Force;return $true}catch{}}}catch{};Remove-Item $t -Force -EA SilentlyContinue;return $false};" ^
  "if(-not(dl $r2 $bs)){dls $gh $bs|Out-Null};if(-not(dl $r2 $loc)){dls $gh $loc|Out-Null};" ^
  "dl '%REMOTE_DGC_PS1_R2%' '%DG%\dgc.ps1'|Out-Null;if(-not(Test-Path '%DG%\dgc.ps1')){dls '%REMOTE_DGC_PS1%' '%DG%\dgc.ps1'|Out-Null};" ^
  "dl '%REMOTE_DG_PS1_R2%' '%DG%\dg.ps1'|Out-Null;if(-not(Test-Path '%DG%\dg.ps1')){dls '%REMOTE_DG_PS1%' '%DG%\dg.ps1'|Out-Null};" ^
  "dl '%REMOTE_DGC_CMD_R2%' '%DG%\dgc.cmd'|Out-Null;dl '%REMOTE_DG_CMD_R2%' '%DG%\dg.cmd'|Out-Null" ^
  >nul 2>&1

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

echo [graperoot] Error: bootstrap unavailable and local launcher missing.
if /i "%INSTALL_METHOD%"=="scoop" (
  echo [graperoot] Scoop is installed, but the local launcher payload is missing.
)
echo [graperoot] Run this once to repair the installation:
echo [graperoot]   %REPAIR_CMD%
exit /b 1
