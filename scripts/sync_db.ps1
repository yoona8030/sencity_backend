# sync_db.ps1  (PowerShell 5.1 compatible, ASCII-only messages)
Param(
  [string]$Owner = "",
  [string]$Repo  = "",
  [string]$AssetName    = "db_release.sqlite3",
  [string]$ShaAssetName = "db_release.sha256.txt"
)

$ErrorActionPreference = "Stop"
# GitHub requires TLS1.2 on PS 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-RepoRoot {
  # assume this script is under <repo>\scripts\sync_db.ps1
  try {
    $root = Split-Path -Parent $PSScriptRoot
    if (-not $root) { $root = Split-Path -Parent $PSCommandPath }
    return $root
  } catch { return (Get-Location).Path }
}

function Parse-GitRemote([string]$url) {
  if ($url -match "github\.com[:/](?<owner>[^/]+)/(?<repo>[^/.]+)(\.git)?$") {
    return @($matches.owner, $matches.repo)
  }
  return @("","")
}

$root = Get-RepoRoot
Set-Location $root

# Detect OWNER/REPO from origin if not provided
if (-not $Owner -or -not $Repo) {
  try {
    $remote = git config --get remote.origin.url 2>$null
    $pair   = Parse-GitRemote $remote
    $Owner  = $pair[0]; $Repo = $pair[1]
  } catch { }
}
if (-not $Owner -or -not $Repo) {
  throw "Cannot determine OWNER/REPO. Pass -Owner and -Repo explicitly."
}

# Paths in repo root
$targetDb    = Join-Path $root "db.sqlite3"
$versionFile = Join-Path $root ".db_version"
$tmpDownload = Join-Path $env:TEMP $AssetName

# Query latest release
$api = "https://api.github.com/repos/$Owner/$Repo/releases/latest"
$headers = @{ "Accept"="application/vnd.github+json" }
if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $($env:GITHUB_TOKEN)" }

try {
  $rel = Invoke-RestMethod -Headers $headers -Uri $api -Method GET
} catch {
  throw "Failed to fetch latest release from GitHub. $_"
}

$remoteTag = $rel.tag_name

# PowerShell 5.1: no ternary operator
$localTag = ""
if (Test-Path $versionFile) {
  $localTag = (Get-Content $versionFile -Raw).Trim()
}

if (($remoteTag -eq $localTag) -and (Test-Path $targetDb)) {
  Write-Host "DB is already up-to-date ($remoteTag)."
  exit 0
}

# Find assets
$asset = $rel.assets | Where-Object { $_.name -eq $AssetName } | Select-Object -First 1
if (-not $asset) { throw "Asset not found in release: $AssetName" }
$downloadUrl = $asset.browser_download_url

# Download db asset
Invoke-WebRequest -Headers @{ "Accept"="application/octet-stream" } `
  -Uri $downloadUrl -OutFile $tmpDownload

# Optional: verify SHA256 if sha file exists
$shaAsset = $rel.assets | Where-Object { $_.name -eq $ShaAssetName } | Select-Object -First 1
if ($shaAsset) {
  $shaTmp = Join-Path $env:TEMP $ShaAssetName
  Invoke-WebRequest -Headers @{ "Accept"="application/octet-stream" } `
    -Uri $shaAsset.browser_download_url -OutFile $shaTmp

  $expected = (Get-Content $shaTmp -Raw).Trim().ToLower()
  # Extract first 64-hex if file has extra text
  if ($expected -notmatch "^[0-9a-f]{64}$") {
    $m = Select-String -Path $shaTmp -Pattern "[0-9a-fA-F]{64}" | Select-Object -First 1
    if ($m) { $expected = $m.Matches[0].Value.ToLower() }
  }

  $actual = (Get-FileHash $tmpDownload -Algorithm SHA256).Hash.ToLower()
  if ($expected -ne $actual) {
    Remove-Item -Force $tmpDownload -ErrorAction SilentlyContinue
    throw "SHA256 mismatch. expected=$expected actual=$actual"
  }
}

# Backup then replace
if (Test-Path $targetDb) {
  $ts = Get-Date -Format "yyyyMMdd-HHmmss"
  Copy-Item $targetDb "$targetDb.bak.$ts"
}
Move-Item -Force $tmpDownload $targetDb
Set-Content -Path $versionFile -Value $remoteTag

Write-Host "Sync done: $targetDb (tag=$remoteTag)"
