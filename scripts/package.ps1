param(
  [switch]$AllowDirty,
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = $null

$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
if ($Hermes) {
  $Candidate = Join-Path (Split-Path -Parent $Hermes.Source) "python.exe"
  if (Test-Path -LiteralPath $Candidate) { $Python = $Candidate }
}
if (-not $Python) {
  foreach ($Name in @("python3", "python")) {
    $Found = Get-Command $Name -ErrorAction SilentlyContinue
    if ($Found) { $Python = $Found.Source; break }
  }
}
if (-not $Python) { throw "Python 3 was not found." }

$Arguments = @((Join-Path $PSScriptRoot "build_release.py"))
if ($AllowDirty) { $Arguments += "--allow-dirty" }
if ($SkipTests) { $Arguments += "--skip-tests" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
