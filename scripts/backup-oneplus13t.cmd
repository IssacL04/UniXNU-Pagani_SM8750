@echo off
setlocal DisableDelayedExpansion
set "P13_SCRIPT=%~f0"
set "P13_DEST=%~1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command "$code = Get-Content -LiteralPath $env:P13_SCRIPT -Raw; & ([scriptblock]::Create(($code -split '(?m)^# POWERSHELL\r?$', 2)[1]))"
exit /b %errorlevel%
# POWERSHELL
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

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

function Read-Size([string]$Device, [string]$Option = '--getsize64') {
    $value = Read-Phone "blockdev $Option $Device"
    if ($value -notmatch '^[0-9]+$' -or [long]$value -le 0) { throw "Cannot read size of $Device : $value" }
    return [long]$value
}

function Gpt-Ranges([byte[]]$Header, [long]$Sector, [long]$DiskBytes) {
    if ($Sector -notin @(512, 4096) -or $Header.Length -ne $Sector -or
        [Text.Encoding]::ASCII.GetString($Header, 0, 8) -ne 'EFI PART' -or $DiskBytes % $Sector -ne 0) {
        throw 'Invalid GPT signature or logical block size.'
    }
    $headerSize = [BitConverter]::ToUInt32($Header, 12)
    $current = [BitConverter]::ToUInt64($Header, 24)
    $backup = [BitConverter]::ToUInt64($Header, 32)
    $first = [BitConverter]::ToUInt64($Header, 40)
    $last = [BitConverter]::ToUInt64($Header, 48)
    $table = [BitConverter]::ToUInt64($Header, 72)
    $entries = [BitConverter]::ToUInt32($Header, 80)
    $entrySize = [BitConverter]::ToUInt32($Header, 84)
    [long]$blocks = $DiskBytes / $Sector
    $tableBlocks = [Math]::Ceiling(([double]$entries * $entrySize) / $Sector)
    if ($headerSize -lt 92 -or $headerSize -gt $Sector -or $current -ne 1 -or $backup -ne ($blocks - 1) -or
        $entries -eq 0 -or $entrySize -lt 128 -or $table -lt 2 -or $table -gt $first -or
        $tableBlocks -gt ($first - $table) -or $first -gt $last -or $last -ge $backup -or
        $tableBlocks -gt ($backup - $last - 1) -or $first -gt (16MB / $Sector) -or
        ($blocks - $last - 1) -gt (16MB / $Sector)) {
        throw 'Unexpected GPT geometry; refusing to guess disk offsets.'
    }
    return @(
        [pscustomobject]@{ Label = 'primary'; Skip = [long]0; Count = [long]$first },
        [pscustomobject]@{ Label = 'backup'; Skip = [long]($last + 1); Count = [long]($blocks - $last - 1) }
    )
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
    foreach ($sector in @(512, 4096)) {
        $header = New-Object byte[] $sector
        [Text.Encoding]::ASCII.GetBytes('EFI PART').CopyTo($header, 0)
        [BitConverter]::GetBytes([uint32]92).CopyTo($header, 12)
        [long]$blocks = 64MB / $sector
        [long]$first = 2 + (16384 / $sector)
        foreach ($pair in @(@(24, 1), @(32, ($blocks - 1)), @(40, $first), @(48, ($blocks - $first)), @(72, 2))) {
            [BitConverter]::GetBytes([uint64]$pair[1]).CopyTo($header, $pair[0])
        }
        [BitConverter]::GetBytes([uint32]128).CopyTo($header, 80)
        [BitConverter]::GetBytes([uint32]128).CopyTo($header, 84)
        $ranges = @(Gpt-Ranges $header $sector 64MB)
        if ($ranges[0].Count -ne $first -or ($ranges[1].Skip + $ranges[1].Count) -ne $blocks) { throw 'GPT range test failed.' }
        [BitConverter]::GetBytes([uint64]2).CopyTo($header, 40)
        Assert-Throws { Gpt-Ranges $header $sector 64MB }
        $header[0] = 0
        Assert-Throws { Gpt-Ranges $header $sector 64MB }
    }
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
    Write-Host 'PASS: ADB states, offline checks, GPT geometry, binary stream, stderr separation, truncated/oversize reads, process failures, binary status framing.'
}

try {
    if ($env:P13_DEST -eq '--self-test') { Self-Test; exit 0 }
    if (!$env:P13_DEST) { throw 'Usage: backup-oneplus13t.cmd "E:\13T-backup"' }
    $destination = [IO.Path]::GetFullPath($env:P13_DEST)
    if ($destination -notmatch '^[A-Za-z]:\\') { throw 'Choose a local Windows drive, for example E:\13T-backup.' }
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
        (Read-Phone 'readlink -f /dev/block/by-name/ocdt') -ne '/dev/block/sdd5') {
        throw 'Partition layout differs from the supplied OnePlus 13T listing.'
    }
    # boot is already backed up by the user; firmware, super, logs and swap are excluded.
    $partitions = @(
        'persist', 'modemst1', 'modemst2', 'fsg', 'fsc',
        'oplusdycnvbk', 'oplusstanvbk_a', 'oplusstanvbk_b', 'mdm1oemnvbktmp',
        'cdt', 'ddr', 'engineering_cdt_a', 'engineering_cdt_b', 'ocdt', 'dinfo',
        'oplusreserve1', 'oplusreserve2', 'oplusreserve3', 'oplusreserve5', 'param', 'ompdt',
        'misc', 'keystore', 'frp', 'ssd', 'devinfo', 'uefivarstore', 'secdata', 'spunvm', 'vm-persist',
        'init_boot_a', 'init_boot_b', 'vendor_boot_a', 'vendor_boot_b', 'recovery_a', 'recovery_b',
        'dtbo_a', 'dtbo_b', 'vbmeta_a', 'vbmeta_b', 'vbmeta_system_a', 'vbmeta_system_b',
        'vbmeta_vendor_a', 'vbmeta_vendor_b', 'metadata', 'userdata'
    )
    $jobs = @()
    Write-Host 'Checking partition sizes and GPT (read only)...'
    foreach ($name in $partitions) {
        $device = "/dev/block/by-name/$name"
        $bytes = Read-Size $device
        $jobs += [pscustomobject]@{ Name = "$name.img"; Device = $device; Offset = [long]0; Bytes = $bytes; Command = "cat $device" }
    }
    foreach ($disk in @('sda', 'sdb', 'sdc', 'sdd', 'sde', 'sdf')) {
        $device = "/dev/block/$disk"
        $sector = Read-Size $device '--getss'
        $diskBytes = Read-Size $device
        $probe = New-Object IO.MemoryStream
        try {
            Invoke-Capture $script:Adb (Phone-Args "dd if=$device bs=$sector skip=1 count=1" -Binary) $probe $sector -Framed
            $ranges = @(Gpt-Ranges $probe.ToArray() $sector $diskBytes)
        } finally { $probe.Dispose() }
        foreach ($range in $ranges) {
            $jobs += [pscustomobject]@{ Name = "$disk-gpt-$($range.Label).bin"; Device = $device; Offset = [long]($range.Skip * $sector); Bytes = [long]($range.Count * $sector); Command = "dd if=$device bs=$sector skip=$($range.Skip) count=$($range.Count)" }
        }
    }
    [long]$total = ($jobs | Measure-Object -Property Bytes -Sum).Sum
    Write-Host ("Selected {0} partitions plus GPT: {1:N2} GiB (raw userdata includes unused space)." -f $partitions.Count, ($total / 1GB))
    if ($drive.AvailableFreeSpace -lt ($total + 1GB)) { throw 'Not enough free space; reserve the displayed size plus 1 GiB.' }
    $output = Join-Path $destination (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
    $null = New-Item -ItemType Directory -Path $output
    $manifest = Join-Path $output 'manifest.csv'
    $info = "serial=$script:Serial`r`nmodel=$(Read-Phone 'getprop ro.product.model')`r`nfingerprint=$(Read-Phone 'getprop ro.build.fingerprint')`r`nslot=$(Read-Phone 'getprop ro.boot.slot_suffix')`r`nboot partitions were excluded because they were already backed up.`r`n"
    [IO.File]::WriteAllText((Join-Path $output 'device.txt'), $info)
    Write-Host "Destination: $output"
    foreach ($job in ($jobs | Sort-Object { $_.Name -eq 'userdata.img' }, Bytes)) {
        Check-Offline
        $partial = Join-Path $output ($job.Name + '.partial')
        Write-Host ("Reading {0} ({1:N2} GiB)" -f $job.Name, ($job.Bytes / 1GB))
        $stream = [IO.File]::Open($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try {
            Invoke-Capture $script:Adb (Phone-Args $job.Command -Binary) $stream $job.Bytes -Framed
            $stream.Flush($true)
        } finally { $stream.Dispose() }
        Write-Host "Verifying $($job.Name)..."
        if ((Get-Item -LiteralPath $partial).Length -ne $job.Bytes) { throw 'Saved file length mismatch.' }
        $hash = (Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash
        $final = Join-Path $output $job.Name
        [IO.File]::Move($partial, $final)
        [pscustomobject]@{ File = $job.Name; Device = $job.Device; OffsetBytes = $job.Offset; Bytes = $job.Bytes; SHA256 = $hash } |
            Export-Csv -LiteralPath $manifest -NoTypeInformation -Append -Encoding UTF8
    }
    Write-Host "COMPLETE: $output"
    Write-Host 'Keep your existing boot backup with these files. This is not a full factory firmware backup.'
    exit 0
} catch {
    Write-Host "STOPPED: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'Backup is NOT complete. Existing images are retained; .partial files are not valid backups.'
    exit 1
}
