$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$TestRoot = [System.IO.Path]::GetFullPath((Join-Path $TempRoot (
  "hermes-connector-install-" + [guid]::NewGuid().ToString("N")
)))
if (-not $TestRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Unsafe temporary installer test path"
}

$OriginalPath = $env:PATH
$OriginalLocalAppData = $env:LOCALAPPDATA
New-Item -ItemType Directory -Path $TestRoot | Out-Null
try {
  $RealPython = $null
  foreach ($Candidate in @(Get-Command python -CommandType Application -All -ErrorAction SilentlyContinue)) {
    try {
      $CandidateFile = Get-Item -LiteralPath $Candidate.Source
      if ($CandidateFile.Length -eq 0) { continue }
      $Probe = & $Candidate.Source -c "import sys; print('hermes-python-ok' if sys.version_info >= (3, 10) else '')" 2>$null
      if ($LASTEXITCODE -eq 0 -and $Probe -eq "hermes-python-ok") {
        $RealPython = $Candidate.Source
        break
      }
    }
    catch {}
  }
  if (-not $RealPython) { throw "The installer test needs Python 3.10 or newer" }

  # Reproduce a normal Windows PATH with more than one command of the same
  # name. The installer must skip a broken candidate and use the next one.
  $BadShimDir = Join-Path $TestRoot "bad-python"
  $GoodShimDir = Join-Path $TestRoot "good-python"
  New-Item -ItemType Directory -Path $BadShimDir, $GoodShimDir | Out-Null
  [System.IO.File]::WriteAllBytes(
    (Join-Path $BadShimDir "python3.exe"),
    [byte[]]@()
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $BadShimDir "python3.cmd"),
    "@echo off`r`nexit /b 1`r`n"
  )
  [System.IO.File]::WriteAllText(
    (Join-Path $GoodShimDir "python3.cmd"),
    ("@echo off`r`n`"{0}`" %*`r`n" -f $RealPython)
  )
  $env:PATH = "$BadShimDir;$GoodShimDir;$OriginalPath"
  $env:LOCALAPPDATA = Join-Path $TestRoot "empty-localappdata"

  # A user-defined command named `hermes` must not make install.ps1 dereference
  # an empty .Source path. Only an actual application is a Python-location hint.
  function global:hermes { throw "the test function must never be invoked" }
  & (Join-Path $Root "scripts\install.ps1") `
    --hermes-home $TestRoot `
    --no-enable `
    --no-show-code
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  $Payload = Join-Path $TestRoot "plugins\hermes-connector\plugin.yaml"
  if (-not (Test-Path -LiteralPath $Payload)) {
    throw "PowerShell companion install did not create the payload"
  }
  if (-not (Select-String -LiteralPath $Payload -Pattern '^version: 0\.2\.1$' -Quiet)) {
    throw "PowerShell companion install produced the wrong version"
  }

  $CmdHome = Join-Path $TestRoot "double-click-home"
  $CmdInstaller = Join-Path $Root "scripts\Install Hermes Connector.cmd"
  $env:HERMES_CONNECTOR_NO_PAUSE = "1"
  $CmdLine = ('"{0}" --hermes-home "{1}" --no-enable --no-show-code' -f $CmdInstaller, $CmdHome)
  & $env:ComSpec /d /s /c $CmdLine
  if ($LASTEXITCODE -ne 0) { throw "Double-click Windows installer failed with $LASTEXITCODE" }
  $CmdPayload = Join-Path $CmdHome "plugins\hermes-connector\plugin.yaml"
  if (-not (Test-Path -LiteralPath $CmdPayload)) {
    throw "Double-click Windows installer did not create the payload"
  }
  Write-Host "PowerShell companion install passed: $Payload"
}
finally {
  $env:PATH = $OriginalPath
  $env:LOCALAPPDATA = $OriginalLocalAppData
  Remove-Item Env:\HERMES_CONNECTOR_NO_PAUSE -ErrorAction SilentlyContinue
  Remove-Item Function:\hermes -ErrorAction SilentlyContinue
  if ($TestRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
      (Split-Path -Leaf $TestRoot).StartsWith("hermes-connector-install-")) {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force
  }
}
