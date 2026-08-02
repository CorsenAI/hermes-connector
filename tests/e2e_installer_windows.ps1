$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$TempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$TestRoot = [System.IO.Path]::GetFullPath((Join-Path $TempRoot (
  "hermes-connector-install-" + [guid]::NewGuid().ToString("N")
)))
if (-not $TestRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Unsafe temporary installer test path"
}

New-Item -ItemType Directory -Path $TestRoot | Out-Null
try {
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
  Remove-Item Env:\HERMES_CONNECTOR_NO_PAUSE -ErrorAction SilentlyContinue
  Remove-Item Function:\hermes -ErrorAction SilentlyContinue
  if ($TestRoot.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
      (Split-Path -Leaf $TestRoot).StartsWith("hermes-connector-install-")) {
    Remove-Item -LiteralPath $TestRoot -Recurse -Force
  }
}
