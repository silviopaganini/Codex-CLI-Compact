@echo off
:: dg — stable Windows bootstrap for Codex CLI + dual-graph
:: Keeps the entrypoint minimal and delegates launcher logic to PowerShell.

setlocal

set "DG=%USERPROFILE%\.dual-graph"
set "LOCAL_PS1=%DG%\dg.ps1"
set "LOCAL_CMD=%DG%\dg.cmd"
set "PENDING_CMD=%DG%\dg.cmd.new"
set "BOOTSTRAP_PS1=%TEMP%\dual_graph_dg_bootstrap.ps1"
set "REMOTE_PS1=https://raw.githubusercontent.com/kunal12203/Codex-CLI-Compact/main/bin/dg.ps1"
set "REMOTE_PS1_R2=https://pub-18426978d5a14bf4a60ddedd7d5b6dab.r2.dev/dg.ps1"
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
  if exist "%SCOOP%\shims\dg.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
) else (
  if exist "%USERPROFILE%\scoop\shims\dg.cmd" (
    set "INSTALL_METHOD=scoop"
    set "REPAIR_CMD=scoop update dual-graph"
  )
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$gh='%REMOTE_PS1%';$r2='%REMOTE_PS1_R2%';$loc='%LOCAL_PS1%';$bs='%BOOTSTRAP_PS1%';" ^
  "function dl($u,$o){$t=$o+'.tmp';try{Invoke-WebRequest $u -OutFile $t -UseBasicParsing -TimeoutSec 15;if((Test-Path $t)-and(Get-Item $t).Length-gt 1024){Move-Item $t $o -Force;return $true}}catch{};Remove-Item $t -Force -EA SilentlyContinue;return $false};" ^
  "function dls($u,$o){$t=$o+'.tmp';try{Invoke-WebRequest $u -OutFile $t -UseBasicParsing -TimeoutSec 15;if((Test-Path $t)-and(Get-Item $t).Length-gt 1024){try{[void][System.Management.Automation.ScriptBlock]::Create((Get-Content $t -Raw));Move-Item $t $o -Force;return $true}catch{}}}catch{};Remove-Item $t -Force -EA SilentlyContinue;return $false};" ^
  "if(-not(dls $r2 $bs)){dls $gh $bs|Out-Null};if(-not(dls $r2 $loc)){dls $gh $loc|Out-Null};" ^
  "dl '%REMOTE_GR_CMD_R2%' '%DG%\graperoot.cmd'|Out-Null;if(-not(Test-Path '%DG%\graperoot.cmd')){dl '%REMOTE_GR_CMD%' '%DG%\graperoot.cmd'|Out-Null};" ^
  "dl '%REMOTE_GR_PS1_R2%' '%DG%\graperoot.ps1'|Out-Null;if(-not(Test-Path '%DG%\graperoot.ps1')){dl '%REMOTE_GR_PS1%' '%DG%\graperoot.ps1'|Out-Null}" ^
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

echo [dg] Error: bootstrap unavailable and local launcher missing.
if /i "%INSTALL_METHOD%"=="scoop" (
  echo [dg] Scoop is installed, but the local launcher payload is missing.
)
echo [dg] Run this once to repair the installation:
echo [dg]   %REPAIR_CMD%
exit /b 1
