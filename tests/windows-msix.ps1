# CI only: test the real launcher in a disposable MSIX identity, without using
# ChatGPT, customer credentials, cloud APIs, or changing machine-wide policy.
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$work = Join-Path $env:RUNNER_TEMP ('Creative Kit MSIX ' + [guid]::NewGuid().ToString('N'))
$payload = Join-Path $work 'payload'
$packageName = 'BytePlusKit.Probe' + [guid]::NewGuid().ToString('N')
$subject = 'CN=BytePlus Creative Kit Regression'
$certificate = $null
$trusted = $null
$package = $null
New-Item -ItemType Directory -Path (Join-Path $payload 'bin') -Force | Out-Null
try {
    Copy-Item (Join-Path $repo 'plugins\byteplus-creative-kit-windows\bin\creative-kit.exe') (Join-Path $payload 'bin\creative-kit.exe')
    Add-Type -AssemblyName System.Drawing
    foreach ($size in @(44,50,150)) {
        $bitmap = New-Object Drawing.Bitmap $size,$size
        $bitmap.Save((Join-Path $payload "logo$size.png"), [Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()
    }
    @"
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
 xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
 xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
 IgnorableNamespaces="uap rescap">
 <Identity Name="$packageName" Publisher="$subject" Version="1.0.0.0" ProcessorArchitecture="x64" />
 <Properties><DisplayName>Creative Kit Regression</DisplayName><PublisherDisplayName>Creative Kit Regression</PublisherDisplayName><Logo>logo50.png</Logo></Properties>
 <Resources><Resource Language="en-us" /></Resources>
 <Dependencies><TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.19041.0" MaxVersionTested="10.0.26100.0" /></Dependencies>
 <Applications><Application Id="Probe" Executable="bin\creative-kit.exe" EntryPoint="Windows.FullTrustApplication">
  <uap:VisualElements DisplayName="Creative Kit Regression" Description="Disposable installer test" Square150x150Logo="logo150.png" Square44x44Logo="logo44.png" BackgroundColor="transparent" />
 </Application></Applications>
 <Capabilities><rescap:Capability Name="runFullTrust" /></Capabilities>
</Package>
"@ | Set-Content -LiteralPath (Join-Path $payload 'AppxManifest.xml') -Encoding UTF8
    $sdk = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\makeappx.exe" | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $sdk) { throw 'Windows SDK makeappx.exe is required for the MSIX regression.' }
    $signTool = Join-Path $sdk.DirectoryName 'signtool.exe'
    $archive = Join-Path $work 'probe.msix'
    & $sdk.FullName pack /d $payload /p $archive /o | Out-Null
    if ($LASTEXITCODE) { throw 'MSIX packing failed.' }
    $certificate = New-SelfSignedCertificate -Type CodeSigningCert -Subject $subject -CertStoreLocation Cert:\CurrentUser\My -HashAlgorithm SHA256
    $publicCertificate = Join-Path $work 'test.cer'
    Export-Certificate -Cert $certificate -FilePath $publicCertificate | Out-Null
    $trusted = Import-Certificate -FilePath $publicCertificate -CertStoreLocation Cert:\CurrentUser\TrustedPeople
    & $signTool sign /fd SHA256 /s My /sha1 $certificate.Thumbprint $archive | Out-Null
    if ($LASTEXITCODE) { throw 'MSIX signing failed.' }
    Add-AppxPackage -Path $archive
    $package = Get-AppxPackage -Name $packageName
    if (-not $package) { throw 'Disposable MSIX package was not registered.' }
    $report = Join-Path $work 'result.json'
    $python = (Get-Command python.exe).Source
    $script = Join-Path $repo 'tests\desktop_integration.py'
    $probeArgs = '"{0}" --msix-report "{1}"' -f $script, $report
    Invoke-CommandInDesktopPackage -PackageFamilyName $package.PackageFamilyName -AppId Probe -Command $python -Args $probeArgs -PreventBreakaway
    $startupDeadline = (Get-Date).AddSeconds(45)
    while (-not (Test-Path -LiteralPath $report)) {
        if ((Get-Date) -gt $startupDeadline) { throw 'MSIX probe process did not start.' }
        Start-Sleep -Seconds 1
    }
    $deadline = (Get-Date).AddMinutes(15)
    do {
        $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($result.state -ne 'running') { break }
        if ((Get-Date) -gt $deadline) { throw 'MSIX bootstrap did not finish within 15 minutes.' }
        Start-Sleep -Seconds 2
    } while ($true)
    Get-Content -LiteralPath ([IO.Path]::ChangeExtension($report, '.log')) -Encoding UTF8
    if ($result.state -ne 'passed') { throw 'Packaged Windows bootstrap regression failed.' }
    Write-Output 'PASS: the real native launcher prepares Python and serves tools inside an MSIX file-system context.'
} finally {
    if ($package) { Remove-AppxPackage -Package $package.PackageFullName }
    if ($trusted) { Remove-Item -LiteralPath ('Cert:\CurrentUser\TrustedPeople\' + $trusted.Thumbprint) }
    if ($certificate) { Remove-Item -LiteralPath ('Cert:\CurrentUser\My\' + $certificate.Thumbprint) }
}
