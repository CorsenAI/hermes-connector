param(
  [switch]$AllowDirty,
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = $null

function Test-Python310([string]$Path) {
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
  & $Path -c "import sys; raise SystemExit(sys.version_info < (3, 10))" *> $null
  return $LASTEXITCODE -eq 0
}

$Hermes = Get-Command hermes -CommandType Application -ErrorAction SilentlyContinue
if ($Hermes -and $Hermes.Source) {
  $Candidate = Join-Path (Split-Path -Parent $Hermes.Source) "python.exe"
  if (Test-Python310 $Candidate) { $Python = $Candidate }
}
if (-not $Python -and $env:LOCALAPPDATA) {
  $BundledPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
  if (Test-Python310 $BundledPython) { $Python = $BundledPython }
}
if (-not $Python) {
  foreach ($Name in @("python3", "python")) {
    $Found = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue
    if ($Found -and (Test-Python310 $Found.Source)) { $Python = $Found.Source; break }
  }
}
if (-not $Python) { throw "Python 3.10 or newer was not found." }

$Arguments = @((Join-Path $PSScriptRoot "build_release.py"))
if ($AllowDirty) { $Arguments += "--allow-dirty" }
if ($SkipTests) { $Arguments += "--skip-tests" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
