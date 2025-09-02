# install_hooks.ps1  (PS 5.1 호환 / ASCII / Git hooks as .bat)
$ErrorActionPreference = "Stop"

# repo root 추정: scripts\ 의 부모가 루트
$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $repoRoot ".git"))) {
  # 예외적 구조면 git로 보정
  try {
    $repoRoot = (git rev-parse --show-toplevel).Trim()
  } catch { throw "Cannot find repo root. Run from inside a Git repo." }
}

$hooks = Join-Path $repoRoot ".git\hooks"
if (-not (Test-Path $hooks)) { throw ".git/hooks not found (did you clone the repo?)" }

$bat = @"
@echo off
REM Auto-sync DB from latest GitHub Release on checkout/merge/rewrite
REM Uses PowerShell to run scripts\sync_db.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\..\scripts\sync_db.ps1"
exit /b 0
"@

$targets = @("post-checkout.bat","post-merge.bat","post-rewrite.bat")
foreach ($t in $targets) {
  $p = Join-Path $hooks $t
  Set-Content -Path $p -Value $bat -Encoding ASCII
  Write-Host "Installed hook: $p"
}

Write-Host "Done. Hooks will run on git checkout/merge/rewrite."
