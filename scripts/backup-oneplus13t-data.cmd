@echo off
setlocal DisableDelayedExpansion
set "P13_SCRIPT=%~f0"
set "P13_DEST=%~1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$code = Get-Content -LiteralPath $env:P13_SCRIPT -Raw; & ([scriptblock]::Create(($code -split '(?m)^# POWERSHELL\r?$', 2)[1]))"
exit /b %errorlevel%
# POWERSHELL
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public class SparseImage : FileStream {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool DeviceIoControl(SafeFileHandle file, uint code, IntPtr input, uint inputSize,
        IntPtr output, uint outputSize, out uint returned, IntPtr overlapped);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    static extern uint GetCompressedFileSizeW(string name, out uint high);
    public SparseImage(string path) : base(path, FileMode.CreateNew, FileAccess.Write, FileShare.None) {
        uint returned;
        if (!DeviceIoControl(SafeFileHandle, 0x900C4, IntPtr.Zero, 0, IntPtr.Zero, 0, out returned, IntPtr.Zero)) {
            int error = Marshal.GetLastWin32Error(); Dispose(); throw new Win32Exception(error);
        }
    }
    public override void Write(byte[] buffer, int offset, int count) {
        if (buffer == null || offset < 0 || count < 0 || offset > buffer.Length - count)
            throw new ArgumentException("Invalid byte range.");
        for (int i = offset; i < offset + count; i++) {
            if (buffer[i] != 0) { base.Write(buffer, offset, count); return; }
        }
        Seek(count, SeekOrigin.Current);
    }
    public static long AllocatedBytes(string path) {
        uint high; uint low = GetCompressedFileSizeW(path, out high);
        if (low == uint.MaxValue && Marshal.GetLastWin32Error() != 0)
            throw new Win32Exception(Marshal.GetLastWin32Error());
        return ((long)high << 32) | low;
    }
}
'@

# Use byte streams: Windows PowerShell's native-command redirection changes binary data.
function Invoke-Capture([string]$Executable, [string]$Arguments, [IO.Stream]$Sink = $null, [long]$Expected = -1, [switch]$Framed) {
    $p = New-Object Diagnostics.Process
    $p.StartInfo.FileName = $Executable
    $p.StartInfo.Arguments = $Arguments
    $p.StartInfo.UseShellExecute = $false
    $p.StartInfo.CreateNoWindow = $true
    $p.StartInfo.RedirectStandardOutput = $true
    $p.StartInfo.RedirectStandardError = $true
    try {
        if (!$p.Start()) { throw 'Cannot start child process.' }
        $stderr = $p.StandardError.ReadToEndAsync()
        if ($null -eq $Sink) {
            $result = $p.StandardOutput.ReadToEnd()
        } else {
            $buffer = New-Object byte[] (4MB)
            [long]$received = 0
            $clock = [Diagnostics.Stopwatch]::StartNew()
            while ($received -lt $Expected -and ($n = $p.StandardOutput.BaseStream.Read($buffer, 0, [int][Math]::Min($buffer.Length, $Expected - $received))) -gt 0) {
                $received += $n
                $Sink.Write($buffer, 0, $n)
                if ($clock.ElapsedMilliseconds -ge 1000) {
                    Write-Progress -Activity 'Reading phone (read only)' -Status ("{0:N2} / {1:N2} GiB" -f ($received / 1GB), ($Expected / 1GB)) -PercentComplete (100.0 * $received / $Expected)
                    $clock.Restart()
                }
            }
            if ($received -ne $Expected) { throw "Short read: expected $Expected bytes, received $received." }
            if ($Framed) {
                $trailer = ''
                while (($b = $p.StandardOutput.BaseStream.ReadByte()) -ge 0) {
                    $trailer += [char]$b
                    if ($trailer.Length -gt 64) { throw 'Unexpected bytes after partition data.' }
                }
                if ($trailer -ne 'P13_STATUS_0_END') { throw 'Device read failed or binary output was altered; backup rejected.' }
            } elseif ($p.StandardOutput.BaseStream.ReadByte() -ne -1) {
                throw "Received more than $Expected bytes."
            }
        }
        $p.WaitForExit()
        $errorText = $stderr.GetAwaiter().GetResult().Trim()
        if ($p.ExitCode -ne 0) { throw "Command failed ($($p.ExitCode)): $errorText" }
        if ($null -eq $Sink) { return $result.Trim() }
    } finally {
        Write-Progress -Activity 'Reading phone (read only)' -Completed
        try { if (!$p.HasExited) { $p.Kill(); $p.WaitForExit() } } catch { }
        $p.Dispose()
    }
}

function Phone-Args([string]$Command, [switch]$Binary) {
    if ($Command.Contains('"') -or $Command.Contains("'")) { throw 'Unexpected shell quoting.' }
    # Windows adb shell can translate LF to CRLF; exec-out preserves binary bytes.
    if ($Binary) { $Command += ' 2>/dev/null; printf P13_STATUS_%s_END $?' }
    if ($script:UseSu) { $Command = "su -c '$Command'" }
    $mode = if ($Binary) { 'exec-out' } else { 'shell -T -n' }
    return "-s $script:Serial $mode `"$Command`""
}

function Read-Phone([string]$Command) {
    return Invoke-Capture $script:Adb (Phone-Args $Command)
}

function Select-Device([string]$Listing) {
    $devices = @($Listing -split '\r?\n' | Where-Object { $_.Trim() -and $_ -notmatch '^List of devices attached' })
    if ($devices.Count -ne 1 -or $devices[0] -notmatch '^([A-Za-z0-9._:-]+)\s+(device|recovery)$') {
        throw 'Connect exactly one authorized ADB device in recovery.'
    }
    return $Matches[1]
}

function Require-Offline([string]$BootMode, [string]$RecoveryVersion, [string]$Mounts) {
    if ($BootMode -ne 'recovery' -and !$RecoveryVersion) {
        throw 'Boot a compatible recovery first. Live Android userdata is not a consistent backup.'
    }
    foreach ($line in ($Mounts -split '\r?\n')) {
        $fields = $line -split '\s+'
        if ($fields.Count -lt 2) { continue }
        if ($fields[1] -match '^/(data|metadata|sdcard)(/|$)' -or
            $fields[0] -match '^/dev/block/((bootdevice/)?by-name/(userdata|metadata)|sda(10|15))$') {
            throw 'Unmount Data and Metadata in recovery first (do NOT format or wipe them).'
        }
    }
}

function Check-Offline {
    Require-Offline (Read-Phone 'getprop ro.bootmode') (Read-Phone 'getprop ro.twrp.version') (Read-Phone 'cat /proc/mounts')
}

function Read-Size([string]$Device) {
    $value = Read-Phone "blockdev --getsize64 $Device"
    if ($value -notmatch '^[0-9]+$' -or [long]$value -le 0) { throw "Cannot read size of $Device : $value" }
    return [long]$value
}

function Assert-Throws([scriptblock]$Action) {
    $threw = $false
    try { & $Action } catch { $threw = $true }
    if (!$threw) { throw 'Self-test expected an error.' }
}

function Self-Test {
    foreach ($state in @('device', 'recovery')) {
        if ((Select-Device "List of devices attached`r`nTEST123`t$state`r`n") -ne 'TEST123') { throw 'ADB device parsing failed.' }
    }
    Assert-Throws { Select-Device "List of devices attached`n" }
    Assert-Throws { Select-Device "A unauthorized`n" }
    Assert-Throws { Select-Device "A device`nB sideload" }
    Require-Offline 'recovery' '' '/dev/root / ext4 ro 0 0'
    Assert-Throws { Require-Offline 'normal' '' '' }
    Assert-Throws { Require-Offline 'recovery' '' '/dev/block/dm-8 /data f2fs rw 0 0' }
    Assert-Throws { Require-Offline 'recovery' '' '/dev/block/sda10 /metadata ext4 ro 0 0' }
    Assert-Throws { Require-Offline 'recovery' '' '/dev/block/sda15 /mnt/other f2fs rw 0 0' }
    $child = (Get-Process -Id $PID).Path
    $source = '$b = New-Object byte[] 65536; for ($i=0; $i -lt $b.Length; $i++) { $b[$i] = $i % 256 }; [Console]::Error.Write(("E" * 131072)); $s=[Console]::OpenStandardOutput(); $s.Write($b,0,$b.Length)'
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($source))
    $stream = New-Object IO.MemoryStream
    try {
        Invoke-Capture $child "-NoProfile -EncodedCommand $encoded" $stream 65536
        $bytes = $stream.ToArray()
        for ($i = 0; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -ne ($i % 256)) { throw 'Binary stream changed.' } }
        Assert-Throws { Invoke-Capture $child "-NoProfile -EncodedCommand $encoded" $stream 65537 }
        Assert-Throws { Invoke-Capture $child "-NoProfile -EncodedCommand $encoded" $stream 65535 }
        Assert-Throws { Invoke-Capture $child '-NoProfile -Command "exit 9"' }
        foreach ($suffix in @('P13_STATUS_0_END', 'P13_STATUS_1_END', '', 'extraP13_STATUS_0_END')) {
            $framedSource = $source + '; [Console]::Write("' + $suffix + '")'
            $framedCode = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($framedSource))
            if ($suffix -eq 'P13_STATUS_0_END') {
                Invoke-Capture $child "-NoProfile -EncodedCommand $framedCode" $stream 65536 -Framed
            } else {
                Assert-Throws { Invoke-Capture $child "-NoProfile -EncodedCommand $framedCode" $stream 65536 -Framed }
            }
        }
    } finally { $stream.Dispose() }
    $testFile = Join-Path ([IO.Path]::GetTempPath()) ('p13-sparse-' + [Guid]::NewGuid().ToString('N'))
    $testDrive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($testFile))
    if ($testDrive.DriveFormat -eq 'NTFS') {
        try {
            $file = New-Object SparseImage $testFile
            try {
                $zeros = New-Object byte[] (1MB)
                $file.Write($zeros, 0, $zeros.Length)
                $file.Write([byte[]]@(0, 10, 13, 26, 255), 0, 5)
                $file.Write($zeros, 0, $zeros.Length)
                $file.SetLength($file.Position)
            } finally { $file.Dispose() }
            $expected = New-Object byte[] (2MB + 5)
            ([byte[]]@(0, 10, 13, 26, 255)).CopyTo($expected, 1MB)
            $sha = [Security.Cryptography.SHA256]::Create()
            try { $expectedHash = [BitConverter]::ToString($sha.ComputeHash($expected)).Replace('-', '') } finally { $sha.Dispose() }
            if ((Get-Item -LiteralPath $testFile).Length -ne $expected.Length -or
                (Get-FileHash -LiteralPath $testFile).Hash -ne $expectedHash -or
                [SparseImage]::AllocatedBytes($testFile) -ge 1MB) { throw 'Sparse image round-trip failed.' }
        } finally { if (Test-Path -LiteralPath $testFile) { Remove-Item -LiteralPath $testFile } }
    }
    Write-Host 'PASS: ADB states, offline checks, binary stream, stderr separation, truncated/oversize reads, process failures, binary status framing, NTFS sparse round-trip.'
}

try {
    if ($env:P13_DEST -eq '--self-test') { Self-Test; exit 0 }
    if (!$env:P13_DEST) { throw 'Usage: backup-oneplus13t-data.cmd "E:\13T-data-backup"' }
    $destination = [IO.Path]::GetFullPath($env:P13_DEST)
    if ($destination -notmatch '^[A-Za-z]:\\') { throw 'Choose a local Windows drive, for example E:\13T-data-backup.' }
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($destination))
    if (!$drive.IsReady -or $drive.DriveFormat -notin @('NTFS', 'exFAT', 'ReFS')) {
        throw 'Use an NTFS, exFAT or ReFS drive. FAT32 cannot hold userdata.img.'
    }
    $script:Adb = Join-Path (Split-Path $env:P13_SCRIPT) 'adb.exe'
    if (!(Test-Path -LiteralPath $script:Adb)) { $script:Adb = (Get-Command adb.exe -ErrorAction Stop).Source }
    $script:Serial = Select-Device (Invoke-Capture $script:Adb 'devices')
    if ('shell_v2' -notin ((Invoke-Capture $script:Adb "-s $script:Serial features") -split '[,\s]+')) {
        throw 'ADB shell_v2 is required. Update platform-tools or use a compatible recovery.'
    }
    $script:UseSu = $false
    if ((Read-Phone 'id') -notmatch '\buid=0\b') {
        $script:UseSu = $true
        if ((Read-Phone 'id') -notmatch '\buid=0\b') { throw 'Root access is required.' }
    }
    Check-Offline
    if ((Read-Phone 'readlink -f /dev/block/by-name/userdata') -ne '/dev/block/sda15' -or
        (Read-Phone 'readlink -f /dev/block/by-name/metadata') -ne '/dev/block/sda10') {
        throw 'Partition layout differs from the supplied OnePlus 13T listing.'
    }
    $partitions = @('metadata', 'userdata')
    $jobs = @()
    Write-Host 'Checking metadata and userdata sizes (read only)...'
    foreach ($name in $partitions) {
        $device = "/dev/block/by-name/$name"
        $bytes = Read-Size $device
        $jobs += [pscustomobject]@{ Name = "$name.img"; Device = $device; Offset = [long]0; Bytes = $bytes; Command = "cat $device" }
    }
    [long]$total = ($jobs | Measure-Object -Property Bytes -Sum).Sum
    Write-Host ("Selected {0} partitions: {1:N2} GiB (raw userdata includes unused space)." -f $partitions.Count, ($total / 1GB))
    $sparse = $drive.DriveFormat -eq 'NTFS'
    if ($sparse) {
        Write-Host ("NTFS sparse images: zero ranges take no disk space. Free: {0:N2} GiB; worst case: {1:N2} GiB." -f ($drive.AvailableFreeSpace / 1GB), ($total / 1GB))
        Write-Host 'Encrypted nonzero data still needs space. Backup stops if the drive fills up.'
        if ($drive.AvailableFreeSpace -lt 1GB) { throw 'At least 1 GiB of free space is required to start.' }
    } elseif ($drive.AvailableFreeSpace -lt ($total + 1GB)) {
        throw 'Not enough free space. Use an NTFS destination for sparse images, or reserve the raw size plus 1 GiB.'
    }
    $output = Join-Path $destination (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $null = New-Item -ItemType Directory -Path $output
    $manifest = Join-Path $output 'manifest.csv'
    $info = "serial=$script:Serial`r`nmodel=$(Read-Phone 'getprop ro.product.model')`r`nfingerprint=$(Read-Phone 'getprop ro.build.fingerprint')`r`nslot=$(Read-Phone 'getprop ro.boot.slot_suffix')`r`nOnly metadata and userdata are included; both are raw partition images.`r`n"
    [IO.File]::WriteAllText((Join-Path $output 'device.txt'), $info)
    Write-Host "Destination: $output"
    foreach ($job in $jobs) {
        Check-Offline
        $partial = Join-Path $output ($job.Name + '.partial')
        Write-Host ("Reading {0} ({1:N2} GiB)" -f $job.Name, ($job.Bytes / 1GB))
        $stream = if ($sparse) { New-Object SparseImage $partial } else { [IO.File]::Open($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None) }
        try {
            Invoke-Capture $script:Adb (Phone-Args $job.Command -Binary) $stream $job.Bytes -Framed
            $stream.SetLength($job.Bytes)
            $stream.Flush($true)
        } finally { $stream.Dispose() }
        Write-Host "Verifying $($job.Name)..."
        if ((Get-Item -LiteralPath $partial).Length -ne $job.Bytes) { throw 'Saved file length mismatch.' }
        $hash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
        $final = Join-Path $output $job.Name
        [IO.File]::Move($partial, $final)
        if ($sparse) { Write-Host ("Size on disk: {0:N2} GiB (logical image: {1:N2} GiB)" -f ([SparseImage]::AllocatedBytes($final) / 1GB), ($job.Bytes / 1GB)) }
        [pscustomobject]@{ File = $job.Name; Device = $job.Device; OffsetBytes = $job.Offset; Bytes = $job.Bytes; SHA256 = $hash } |
            Export-Csv -LiteralPath $manifest -NoTypeInformation -Append -Encoding UTF8
    }
    Write-Host "COMPLETE: $output"
    Write-Host 'Keep metadata.img and userdata.img from this folder together with your existing backups.'
    exit 0
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Backup is NOT complete. Existing images are retained; .partial files are not valid backups.'
    exit 1
}
