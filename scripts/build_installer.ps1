param(
    [string]$IsccPath = "",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$InstallerPath = Join-Path $ProjectRoot "dist-installer\PackingMVP-Setup.exe"
$InstallerHashPath = "$InstallerPath.sha256"

function Assert-LastExitCode {
    param(
        [string]$StepName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName failed with exit code $LASTEXITCODE."
    }
}

if ([string]::IsNullOrWhiteSpace($IsccPath)) {
    $IsccCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    $Candidates = @(
        $IsccCommand.Source,
        "$env:LocalAppData\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:ChocolateyInstall\lib\innosetup\tools\ISCC.exe"
    )
    $IsccPath = $Candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($IsccPath) -or -not (Test-Path $IsccPath)) {
    throw "ISCC.exe not found. Install Inno Setup 6 or pass -IsccPath."
}

Push-Location $ProjectRoot
try {
    $AppVersion = & $PythonExe -c "import pathlib, sys; sys.path.insert(0, str(pathlib.Path(r'$ProjectRoot') / 'src')); import packing_mvp; print(packing_mvp.__version__)"
    Assert-LastExitCode "version discovery"
    $AppVersion = $AppVersion.Trim()

    & (Join-Path $PSScriptRoot "build_exe.ps1") -PythonExe $PythonExe
    Assert-LastExitCode "EXE build"

    & $IsccPath "/DMyAppVersion=$AppVersion" .\installer\packing_installer.iss
    Assert-LastExitCode "Inno Setup build"

    if (-not (Test-Path $InstallerPath)) {
        throw "Installer not found after build: $InstallerPath"
    }

    $InstallerHash = (Get-FileHash -Path $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path $InstallerHashPath -Value "$InstallerHash  $(Split-Path -Leaf $InstallerPath)" -Encoding ascii
    Write-Host "Installer build completed: $ProjectRoot\dist-installer"
}
finally {
    Pop-Location
}
