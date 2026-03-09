param(
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot "build"
$DistRoot = Join-Path $ProjectRoot "dist"

function Assert-LastExitCode {
    param(
        [string]$StepName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE."
    }
}

Push-Location $ProjectRoot
try {
    if (Test-Path $BuildRoot) {
        Remove-Item -Path $BuildRoot -Recurse -Force
    }

    if (Test-Path $DistRoot) {
        Remove-Item -Path $DistRoot -Recurse -Force
    }

    & $PythonExe -m pip install --upgrade pip
    Assert-LastExitCode "pip upgrade"
    & $PythonExe -m pip install -e ".[build]"
    Assert-LastExitCode "dependency installation"
    & $PythonExe -m PyInstaller --noconfirm --clean .\packaging\packing_gui.spec
    Assert-LastExitCode "PyInstaller build"
    Write-Host "EXE build completed: $ProjectRoot\dist\Packing.exe"
}
finally {
    Pop-Location
}
