@echo off
:: dgc — stable Windows bootstrap for Claude Code + dual-graph
:: Keeps the entrypoint minimal and delegates launcher logic to PowerShell.

setlocal

set "DG=%USERPROFILE%\.dual-graph"
set "LOCAL_PS1=%DG%\dgc.ps1"
set "LOCAL_CMD=%DG%\dgc.cmd"
set "PENDING_CMD=%DG%\dgc.cmd.new"
set "BOOTSTRAP_PS1=%TEMP%\dual_graph_dgc_bootstrap.ps1"
set "REMOTE_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dgc.ps1"
set "REMOTE_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dgc.ps1"
set "REMOTE_GR_CMD=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/graperoot.cmd"
set "REMOTE_GR_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/graperoot.ps1"
set "REMOTE_GR_CMD_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/graperoot.cmd"
set "REMOTE_GR_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/graperoot.ps1"
set "INSTALL_METHOD=direct"
set "REPAIR_CMD=irm https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/install.ps1 ^| iex"

if not exist "%DG%" mkdir "%DG%" >nul 2>&1

if exist "%PENDING_CMD%" (
  move /y "%PENDING_CMD%" "%LOCAL_CMD%" >nul 2>&1
)

if defined SCOOP (
  if exist "%SCOOP%\shims\dgc.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
) else (
  if exist "%USERPROFILE%\scoop\shims\dgc.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$gh='%REMOTE_PS1%';$r2='%REMOTE_PS1_R2%';$loc='%LOCAL_PS1%';$bs='%BOOTSTRAP_PS1%';" ^
  "function dl($u,$o){try{Invoke-WebRequest $u -OutFile $o -UseBasicParsing -TimeoutSec 10|Out-Null;return $true}catch{return $false}};" ^
  "if(-not(dl $gh $loc)){dl $r2 $loc|Out-Null};" ^
  "if(-not(dl $gh $bs)){dl $r2 $bs|Out-Null};" ^
  "dl '%REMOTE_GR_CMD%' '%DG%\graperoot.cmd'|Out-Null;if(-not(Test-Path '%DG%\graperoot.cmd')){dl '%REMOTE_GR_CMD_R2%' '%DG%\graperoot.cmd'|Out-Null};" ^
  "dl '%REMOTE_GR_PS1%' '%DG%\graperoot.ps1'|Out-Null;if(-not(Test-Path '%DG%\graperoot.ps1')){dl '%REMOTE_GR_PS1_R2%' '%DG%\graperoot.ps1'|Out-Null}" ^
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

echo [dgc] Error: bootstrap unavailable and local launcher missing.
if /i "%INSTALL_METHOD%"=="scoop" (
  echo [dgc] Scoop is installed, but the local launcher payload is missing.
)
echo [dgc] Run this once to repair the installation:
echo [dgc]   %REPAIR_CMD%
exit /b 1
