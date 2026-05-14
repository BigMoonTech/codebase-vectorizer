# Windows shim: find a usable Python 3.10-3.13 and hand off to bootstrap.py.
# Skips the Microsoft Store stub (visible under \WindowsApps\).
$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition

function Test-PyVersion {
  param([string]$Exe, [string[]]$ExtraArgs = @())
  try {
    $allArgs = $ExtraArgs + @('-c', 'import sys;print("%d.%d"%sys.version_info[:2])')
    $out = & $Exe @allArgs 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return $out.Trim()
  } catch {
    return $null
  }
}

function Find-WorkablePython {
  foreach ($v in '3.13','3.12','3.11','3.10') {
    $ver = Test-PyVersion -Exe 'py' -ExtraArgs @("-$v")
    if ($ver -in '3.10','3.11','3.12','3.13') {
      return @{ Exe = 'py'; ExtraArgs = @("-$v") }
    }
  }
  foreach ($name in 'python','python3') {
    $cmds = Get-Command $name -All -ErrorAction SilentlyContinue
    foreach ($cmd in $cmds) {
      if ($cmd.Source -like '*WindowsApps\python*') { continue }
      $ver = Test-PyVersion -Exe $cmd.Source
      if ($ver -in '3.10','3.11','3.12','3.13') {
        return @{ Exe = $cmd.Source; ExtraArgs = @() }
      }
    }
  }
  return $null
}

$pyChoice = Find-WorkablePython
if (-not $pyChoice) {
  Write-Error @"
codebase-vectorizer needs Python 3.10-3.13 on PATH.
Install Python 3.12:  winget install Python.Python.3.12
Then re-run.
"@
  exit 1
}

$exe = $pyChoice.Exe
$pre = $pyChoice.ExtraArgs
$allArgs = $pre + @((Join-Path $scriptDir 'bootstrap.py')) + $args

& $exe @allArgs
exit $LASTEXITCODE
