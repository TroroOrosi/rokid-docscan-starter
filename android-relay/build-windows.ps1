param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GradleArguments = @("assembleDebug")
)

$ErrorActionPreference = "Stop"
$GradleVersion = "9.4.1"
$ExpectedSha256 = "2ab2958f2a1e51120c326cad6f385153bb11ee93b3c216c5fccebfdfbb7ec6cb"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CacheRoot = Join-Path $env:LOCALAPPDATA "RokidDocScan\gradle"
$ZipPath = Join-Path $CacheRoot "gradle-$GradleVersion-bin.zip"
$DistributionDir = Join-Path $CacheRoot "gradle-$GradleVersion"
$GradleBat = Join-Path $DistributionDir "bin\gradle.bat"

New-Item -ItemType Directory -Force -Path $CacheRoot | Out-Null

if (-not (Test-Path $GradleBat)) {
    if (-not (Test-Path $ZipPath)) {
        $Uri = "https://services.gradle.org/distributions/gradle-$GradleVersion-bin.zip"
        Invoke-WebRequest -UseBasicParsing -Uri $Uri -OutFile $ZipPath
    }

    $ActualSha256 = (Get-FileHash -Algorithm SHA256 -Path $ZipPath).Hash.ToLowerInvariant()
    if ($ActualSha256 -ne $ExpectedSha256) {
        Remove-Item -Force $ZipPath
        throw "Gradle archive SHA-256 mismatch. Download was removed."
    }

    if (Test-Path $DistributionDir) {
        Remove-Item -Recurse -Force $DistributionDir
    }
    Expand-Archive -Path $ZipPath -DestinationPath $CacheRoot -Force
}

& $GradleBat -p $ProjectDir @GradleArguments
exit $LASTEXITCODE
