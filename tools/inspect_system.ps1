<#
.SYNOPSIS
    Collects read-only hardware, driver, and SDK information for the Universal Door Card Reader.

.DESCRIPTION
    Run this with the reader/encoder connected. It writes a text report under .\reports and also
    prints it to the console. It does not install drivers, start services, or modify hardware.
    Administrator rights are not required, though some service details may be limited.
#>

[CmdletBinding()]
param(
    [string]$OutputDirectory
)

$scriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = Split-Path -Parent $PSCommandPath
}
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = (Get-Location).Path
}
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $scriptRoot "..\reports"
}

$ErrorActionPreference = "Continue"
$lines = [System.Collections.Generic.List[string]]::new()

function Add-Section {
    param([string]$Title)
    $lines.Add("")
    $lines.Add("=" * 78)
    $lines.Add($Title)
    $lines.Add("=" * 78)
}

function Add-Lines {
    param([object]$Value)
    if ($null -eq $Value) {
        $lines.Add("(none)")
        return
    }
    $text = ($Value | Out-String -Width 200).TrimEnd()
    if ([string]::IsNullOrWhiteSpace($text)) {
        $lines.Add("(none)")
    }
    else {
        foreach ($line in ($text -split "`r?`n")) {
            $lines.Add($line)
        }
    }
}

Add-Section "Universal Electronic Door Card Reader - System Inspection"
$lines.Add("Generated:      $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss zzz')")
$lines.Add("Computer:       $env:COMPUTERNAME")
$lines.Add("User:           $env:USERDOMAIN\$env:USERNAME")
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
$lines.Add("Administrator:  $isAdmin")
$lines.Add("PowerShell:     $($PSVersionTable.PSVersion)")

Add-Section "Operating System"
try {
    $os = Get-CimInstance Win32_OperatingSystem
    Add-Lines ([PSCustomObject]@{
        Caption = $os.Caption
        Version = $os.Version
        Build = $os.BuildNumber
        Architecture = $os.OSArchitecture
        LastBoot = $os.LastBootUpTime
    })
}
catch {
    Add-Lines "OS query failed: $($_.Exception.Message)"
}

Add-Section "PC/SC Runtime"
$winscard = Join-Path $env:SystemRoot "System32\winscard.dll"
$lines.Add("winscard.dll present: $(Test-Path -LiteralPath $winscard)")
if (Test-Path -LiteralPath $winscard) {
    $version = (Get-Item -LiteralPath $winscard).VersionInfo
    $lines.Add("winscard.dll version: $($version.FileVersion)")
}
Add-Lines (sc.exe query SCardSvr 2>&1)
Add-Lines (sc.exe qc SCardSvr 2>&1)

Add-Section "Smart Card Reader Devices (PnP class)"
try {
    $readerDevices = Get-PnpDevice -Class SmartCardReader -ErrorAction SilentlyContinue |
        Select-Object Status, Class, FriendlyName, InstanceId
    Add-Lines $readerDevices
}
catch {
    Add-Lines "SmartCardReader query failed: $($_.Exception.Message)"
}

Add-Section "Matching PnP Devices (smart/card/reader/ACR/ACS/Brassco/MIFARE/NFC/RFID)"
try {
    $matching = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match "smart|card|reader|ACR|ACS|Brassco|MIFARE|NFC|RFID|OMNIKEY" -or
            $_.PNPClass -in @("SmartCardReader", "SmartCard")
        } |
        Select-Object Status, PNPClass, Name, DeviceID
    Add-Lines $matching
}
catch {
    Add-Lines "PnP matching query failed: $($_.Exception.Message)"
}

Add-Section "USB, Smart Card, and Serial Devices (present only)"
try {
    $usb = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Class -in @("USB", "SmartCardReader", "SmartCard", "Ports", "libusb-win32 devices", "WinUsb") -or
            $_.InstanceId -match "^USB\\VID_"
        } |
        Select-Object Status, Class, FriendlyName, InstanceId
    Add-Lines $usb
}
catch {
    Add-Lines "USB query failed: $($_.Exception.Message)"
}

Add-Section "USB VID/PID Summary"
try {
    $vids = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
        Where-Object { $_.InstanceId -match "^USB\\VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})" } |
        ForEach-Object {
            $match = [regex]::Match($_.InstanceId, "^USB\\VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})")
            [PSCustomObject]@{
                VID = $match.Groups[1].Value.ToUpper()
                PID = $match.Groups[2].Value.ToUpper()
                Name = $_.FriendlyName
                InstanceId = $_.InstanceId
            }
        } |
        Sort-Object VID, PID -Unique
    Add-Lines $vids
}
catch {
    Add-Lines "VID/PID query failed: $($_.Exception.Message)"
}

Add-Section "Installed Programs (filtered)"
try {
    $uninstallKeys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $programs = Get-ItemProperty $uninstallKeys -ErrorAction SilentlyContinue |
        Where-Object {
            $_.DisplayName -match "brassco|card|smart|ACR|ACS|MIFARE|RFID|NFC|encoder|reader|PC/SC|pcsc"
        } |
        Select-Object DisplayName, DisplayVersion, Publisher, InstallLocation |
        Sort-Object DisplayName -Unique
    Add-Lines $programs
}
catch {
    Add-Lines "Installed-program query failed: $($_.Exception.Message)"
}

Add-Section "Brassco Registry References"
try {
    $registryMatches = reg.exe query "HKLM\SOFTWARE" /f "brassco" /s /k 2>&1
    Add-Lines $registryMatches
}
catch {
    Add-Lines "Registry search failed: $($_.Exception.Message)"
}

Add-Section "Python and Project Environment"
$pythonCandidates = @(
    (Join-Path $scriptRoot "..\.venv\Scripts\python.exe"),
    "python.exe",
    "py.exe"
)
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq "python.exe" -or $candidate -eq "py.exe") {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            $lines.Add("$candidate -> $($command.Source)")
        }
    }
    elseif (Test-Path -LiteralPath $candidate) {
        $resolved = (Resolve-Path -LiteralPath $candidate).Path
        $lines.Add("project python -> $resolved")
        try {
            $lines.Add((& $resolved --version 2>&1 | Out-String).Trim())
        }
        catch {
            $lines.Add("version query failed: $($_.Exception.Message)")
        }
        try {
            $packages = & $resolved -m pip list 2>&1 | Select-String -Pattern "PySide6|pyscard|pytest|ruff"
            Add-Lines $packages
        }
        catch {
            $lines.Add("pip list failed: $($_.Exception.Message)")
        }
    }
}

Add-Section "Application Diagnostics"
$projectRoot = (Resolve-Path (Join-Path $scriptRoot "..")).Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $venvPython) {
    Push-Location $projectRoot
    try {
        Add-Lines (& $venvPython -m doorcard.cli --diagnose --no-console-log --log-dir (Join-Path $projectRoot "logs") 2>&1)
        $lines.Add("doorcard diagnose exit code: $LASTEXITCODE")
        Add-Lines (& $venvPython -m doorcard.cli --list-readers --no-console-log --log-dir (Join-Path $projectRoot "logs") 2>&1)
        $lines.Add("doorcard list-readers exit code: $LASTEXITCODE")
    }
    catch {
        Add-Lines "doorcard diagnostics failed: $($_.Exception.Message)"
    }
    finally {
        Pop-Location
    }
}
else {
    $lines.Add("Project virtual environment not found at: $venvPython")
}

Add-Section "Possible Vendor Files in User Directories"
try {
    $searchRoots = @(
        (Join-Path $env:USERPROFILE "Downloads"),
        (Join-Path $env:USERPROFILE "Desktop"),
        (Join-Path $env:USERPROFILE "Documents")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $files = Get-ChildItem -Path $searchRoots -Recurse -Depth 3 -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match "brassco|be-kkyd|kkyd|mifare|encoder|pcsc|pyscard" } |
        Select-Object FullName, Length, LastWriteTime |
        Sort-Object FullName
    Add-Lines $files
}
catch {
    Add-Lines "File search failed: $($_.Exception.Message)"
}

Add-Section "Notes"
$lines.Add("- This report does not prove card/reader compatibility.")
$lines.Add("- Run the app with the reader connected and perform real scans.")
$lines.Add("- Never share secret card keys in a report or support ticket.")
$lines.Add("- Do not attempt to bypass authentication or clone credentials.")

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
}
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$outputPath = Join-Path (Resolve-Path $OutputDirectory).Path "system-inspection-$timestamp.txt"
$lines | Set-Content -LiteralPath $outputPath -Encoding UTF8
$lines | ForEach-Object { Write-Output $_ }
Write-Output ""
Write-Output "Report written to: $outputPath"
