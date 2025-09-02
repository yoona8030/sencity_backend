$repoRoot = &(git rev-parse --show-toplevel) 2>$null
if (-not $repoRoot) { $repoRoot = Split-Path -Parent $PSCommandPath }

$hooksDir = Join-Path $repoRoot ".git\hooks"
if (-not (Test-Path $hooksDir)) { throw ".git/hooks 폴더가 없습니다. (git clone 위치 확인)" }

# post-merge 훅
$postMergePath = Join-Path $hooksDir "post-merge"
@"
#!/bin/sh
powershell.exe -ExecutionPolicy Bypass -File "`"$repoRoot/scripts/sync_db.ps1`""
"@ | Out-File -FilePath $postMergePath -Encoding ascii

# post-checkout 훅
$postCheckoutPath = Join-Path $hooksDir "post-checkout"
@"
#!/bin/sh
powershell.exe -ExecutionPolicy Bypass -File "`"$repoRoot/scripts/sync_db.ps1`""
"@ | Out-File -FilePath $postCheckoutPath -Encoding ascii

Write-Host "Git hooks installed: post-merge, post-checkout"
