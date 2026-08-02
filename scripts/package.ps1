param(
  [switch]$AllowDirty,
  [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = $null

function Test-Python310([string]$Path) {
  if (-not $Path -or -not (Test-Path -LiteralPath $Path)) { return $false }
  try {
    $CandidateFile = Get-Item -LiteralPath $Path
    if ($CandidateFile.Length -eq 0) { return $false }
    $Probe = & $Path -c "import sys; print('hermes-python-ok' if sys.version_info >= (3, 10) else '')" 2>$null
    return $LASTEXITCODE -eq 0 -and $Probe -eq "hermes-python-ok"
  }
  catch {
    return $false
  }
}

foreach ($Hermes in @(Get-Command hermes -CommandType Application -All -ErrorAction SilentlyContinue)) {
  if ($Hermes.Source) {
    $Candidate = Join-Path (Split-Path -Parent $Hermes.Source) "python.exe"
    if (Test-Python310 $Candidate) { $Python = $Candidate; break }
  }
}
if (-not $Python -and $env:LOCALAPPDATA) {
  $BundledPython = Join-Path $env:LOCALAPPDATA "hermes\hermes-agent\venv\Scripts\python.exe"
  if (Test-Python310 $BundledPython) { $Python = $BundledPython }
}
if (-not $Python) {
  foreach ($Name in @("python3", "python")) {
    foreach ($Found in @(Get-Command $Name -CommandType Application -All -ErrorAction SilentlyContinue)) {
      if ($Found.Source -and (Test-Python310 $Found.Source)) {
        $Python = $Found.Source
        break
      }
    }
    if ($Python) { break }
  }
}
if (-not $Python) { throw "Python 3.10 or newer was not found." }

$Arguments = @((Join-Path $PSScriptRoot "build_release.py"))
if ($AllowDirty) { $Arguments += "--allow-dirty" }
if ($SkipTests) { $Arguments += "--skip-tests" }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
