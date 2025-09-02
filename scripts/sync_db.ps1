Param(
  [string]$Owner = "",
  [string]$Repo  = "",
  [string]$AssetName = "db_release.sqlite3",
  [string]$ShaAssetName = "db_release.sha256.txt"
)
$ErrorActionPreference = "Stop"

function Get-RepoRoot {
  try { (git rev-parse --show-toplevel) } catch { Split-Path -Parent $PSCommandPath }
}
function Parse-GitRemote([string]$url) {
  if ($url -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
    return @($matches.owner, $matches.repo)
  }
  return @("","")
}

$root = Get-RepoRoot
Set-Location $root

if (-not $Owner -or -not $Repo) {
  $remote = git config --get remote.origin.url
  $pair   = Parse-GitRemote $remote
  $Owner  = $pair[0]; $Repo = $pair[1]
  if (-not $Owner -or -not $Repo) { Write-Error "OWNER/REPO 자동 인식 실패. 파라미터로 지정하세요."; exit 1 }
}

# ※ 이 레포가 '백엔드 폴더' 자체라고 가정합니다.
$targetDb    = Join-Path $root "db.sqlite3"
$versionFile = Join-Path $root ".db_version"
$tmpDownload = Join-Path $env:TEMP $AssetName

# 최신 Release 조회
$api = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
$headers = @{ "Accept"="application/vnd.github+json" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $($env:GITHUB_TOKEN)" }

try { $rel = Invoke-RestMethod -Headers $headers -Uri $api -Method GET }
catch { Write-Error "GitHub Release 조회 실패: $_"; exit 1 }

$remoteTag = $rel.tag_name
$localTag  = (Test-Path $versionFile) ? (Get-Content $versionFile -Raw) : ""

if ($remoteTag -eq $localTag -and (Test-Path $targetDb)) {
  Write-Host "DB 최신 상태입니다 ($remoteTag). 동기화 생략."
  exit 0
}

# 자산 찾기
$asset = $rel.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
if (-not $asset) { Write-Error "Release에 $AssetName 가 없습니다."; exit 1 }

# 다운로드
Invoke-WebRequest -Headers @{ "Accept"="application/octet-stream" } `
  -Uri $asset.browser_download_url -OutFile $tmpDownload

# SHA256 검증(있을 때만)
$shaAsset = $rel.assets | Where-Object { $_.name -eq $ShaAssetName } | Select-Object -First 1
if ($shaAsset) {
  $shaTmp = Join-Path $env:TEMP $ShaAssetName
  Invoke-WebRequest -Headers @{ "Accept"="application/octet-stream" } `
    -Uri $shaAsset.browser_download_url -OutFile $shaTmp
  $expected = (Get-Content $shaTmp).Split(" ")[0].Trim()
  $actual   = (Get-FileHash $tmpDownload -Algorithm SHA256).Hash.ToLower()
  if ($expected.ToLower() -ne $actual) { Write-Error "SHA256 불일치"; exit 1 }
}

# 백업 후 교체
if (Test-Path $targetDb) {
  $ts = Get-Date -Format "yyyyMMdd-HHmmss"
  Copy-Item $targetDb "$targetDb.bak.$ts"
}
Move-Item -Force $tmpDownload $targetDb
Set-Content -Path $versionFile -Value $remoteTag

Write-Host "동기화 완료: $targetDb (tag=$remoteTag)"
