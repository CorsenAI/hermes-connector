$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Installer = Join-Path $ScriptDir "install.py"
if (-not (Test-Path -LiteralPath $Installer)) {
  $Installer = Join-Path $ScriptDir "install_companion.py"
}

$Python = $null
$Hermes = Get-Command hermes -ErrorAction SilentlyContinue
if ($Hermes) {
  $Candidate = Join-Path (Split-Path -Parent $Hermes.Source) "python.exe"
  if (Test-Path -LiteralPath $Candidate) { $Python = $Candidate }
}
if (-not $Python) {
  $Found = Get-Command python3 -ErrorAction SilentlyContinue
  if (-not $Found) { $Found = Get-Command python -ErrorAction SilentlyContinue }
  if ($Found) { $Python = $Found.Source }
}
if (-not $Python) { throw "Python 3 was not found." }

& $Python $Installer @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
