<#
.SYNOPSIS
    Capture USB traffic of the OMEN keyboard (VID 0C45 / PID 7D1C) while you
    change colors in Light Studio. Run once as Administrator.

.DESCRIPTION
    1. Self-elevates to Administrator (USBPcap needs it).
    2. Verifies the USBPcap filter is actually attached (via tshark -D).
    3. Starts capturing on all available USBPcap interfaces.
    4. Prints the actions to perform in OMEN Gaming Hub / Light Studio.
    5. Stops when you press Enter; saves one .pcap per interface.

    Every step is written to capture.log inside OutDir, so if nothing is
    captured we can see exactly where it failed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\capture_rgb_windows.ps1
    powershell -ExecutionPolicy Bypass -File tools\capture_rgb_windows.ps1 -OutDir D:\Misc\Omen-RGB-Ki\captures
#>
param(
    [string]$OutDir = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'omen_capture'),
    [int]$MaxUsbpcap = 8
)

$ErrorActionPreference = 'Stop'

# ---- logging helpers -----------------------------------------------------
$script:LogFile = $null
function Write-Log {
    param([string]$msg)
    $stamp = Get-Date -Format 'HH:mm:ss.fff'
    $line = "[$stamp] $msg"
    Write-Host $line
    if ($script:LogFile) {
        Add-Content -LiteralPath $script:LogFile -Value $line -Encoding UTF8
    }
}

# ---- 1. self-elevate -------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host '需要管理员权限，正在弹出 UAC 重新启动...' -ForegroundColor Yellow
    New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
    $log = Join-Path $OutDir 'capture.log'
    Set-Content -LiteralPath $log -Value "=== elevated instance started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -Encoding UTF8
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', "`"$PSCommandPath`"",
        '-OutDir', "`"$OutDir`"",
        '-MaxUsbpcap', "$MaxUsbpcap"
    )
    exit
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$script:LogFile = Join-Path $OutDir 'capture.log'
Set-Content -LiteralPath $script:LogFile -Value "=== capture started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" -Encoding UTF8
Write-Log "user=$env:USERNAME  OutDir=$OutDir"

# ---- 2. find tools ---------------------------------------------------------
$usbpcapCmd = @('D:\USBPcap\USBPcapCMD.exe', 'C:\Program Files\USBPcap\USBPcapCMD.exe') |
    Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
$tshark = @('D:\Wireshark\tshark.exe', 'C:\Program Files\Wireshark\tshark.exe', 'tshark') |
    Where-Object {
        if ($_ -match '[\\/]') {
            Test-Path -LiteralPath $_
        } else {
            [bool](Get-Command $_ -ErrorAction SilentlyContinue)
        }
    } | Select-Object -First 1

Write-Log "USBPcapCMD: $(if ($usbpcapCmd) { $usbpcapCmd } else { '未找到' })"
Write-Log "tshark: $(if ($tshark) { $tshark } else { '未找到' })"

if (-not $usbpcapCmd -and -not $tshark) {
    Write-Log '错误: 未找到 USBPcapCMD.exe 或 tshark.exe'
    exit 1
}

# ---- 3. enumerate USBPcap interfaces --------------------------------------
$ifNames = @()
if ($tshark) {
    $interfaces = (& $tshark -D 2>&1) | Where-Object { $_ -match 'USBPcap(\d+)' }
    foreach ($line in $interfaces) {
        if ($line -match 'USBPcap(\d+)') {
            $ifNames += "USBPcap$($Matches[1])"
        }
    }
    Write-Log "tshark -D 发现 $($ifNames.Count) 个 USBPcap 接口: $($ifNames -join ', ')"
    if ($ifNames.Count -eq 0) {
        Write-Log '警告: 没有任何 USBPcap 接口。USBPcap 驱动已安装但未挂到 USB 根集线器上。'
        Write-Log '修复: 重新运行 USBPcap 1.5.4 安装包 (desowin.org/usbpcap) 后重启;'
        Write-Log '      或 设备管理器 -> 查看 -> 显示隐藏设备 -> USB 根集线器 -> 属性 -> 驱动程序 检查。'
    }
}

# ---- 4. start capture ------------------------------------------------------
$procs = @()
if ($tshark -and $ifNames.Count -gt 0) {
    $outFile = Join-Path $OutDir 'omen_all.pcapng'
    $args = @()
    foreach ($n in $ifNames) { $args += '-i'; $args += $n }
    $args += '-w'; $args += $outFile
    Write-Log "使用 tshark 抓取接口: $($ifNames -join ', ') -> $outFile"
    try {
        $p = Start-Process -FilePath $tshark -ArgumentList $args -WindowStyle Hidden -PassThru -ErrorAction Stop
        $procs += $p
        Write-Log "tshark 已启动 PID=$($p.Id)"
    } catch {
        Write-Log "tshark 启动失败: $_"
    }
}

if ($procs.Count -eq 0 -and $usbpcapCmd) {
    Write-Log '改用 USBPcapCMD 并行抓取所有可能接口...'
    foreach ($i in 1..$MaxUsbpcap) {
        $out = Join-Path $OutDir "usbpcap$i.pcap"
        try {
            $p = Start-Process -FilePath $usbpcapCmd -ArgumentList @('-d', "\\.\USBPcap$i", '-o', $out) -WindowStyle Hidden -PassThru -ErrorAction Stop
            Start-Sleep -Milliseconds 800
            if ($p.HasExited) {
                Write-Log "接口 USBPcap$i 不存在或启动失败 (退出码 $($p.ExitCode))"
            } else {
                $procs += $p
                Write-Log "USBPcap$i 抓包中 PID=$($p.Id) -> $out"
            }
        } catch {
            Write-Log "USBPcap$i 启动异常: $_"
        }
    }
}

Start-Sleep -Seconds 3

# ---- 4b. verify capture is actually running ---------------------------------
if ($procs.Count -eq 0) {
    Write-Log '错误: 没有任何抓包进程存活。请把本目录的 capture.log 发给助手。'
    exit 1
}
foreach ($p in $procs) {
    if ($p.HasExited) {
        Write-Log "警告: 抓包进程 PID=$($p.Id) 已退出 (退出码 $($p.ExitCode))"
    } else {
        Write-Log "抓包进程存活: PID=$($p.Id)"
    }
}
$files = Get-ChildItem -Path $OutDir -File -ErrorAction SilentlyContinue
foreach ($f in $files) {
    if ($f.Length -eq 0) {
        Write-Log "注意: $($f.Name) 目前 0 字节（刚启动正常，稍后应增长）"
    } else {
        Write-Log "$($f.Name) 已有 $($f.Length) 字节"
    }
}

Write-Host ''
Write-Host '==================== 抓包已开始 ====================' -ForegroundColor Green
Write-Host '现在请操作 OMEN Gaming Hub / Light Studio：'
Write-Host '  （四分区键盘一次只能改一个分区，逐区改色：）'
Write-Host '  1) 把【分区 1】设为静态纯红 FF0000，等 5 秒'
Write-Host '  2) 把【分区 2】设为静态纯绿 00FF00，等 5 秒'
Write-Host '  3) 把【分区 3】设为静态纯蓝 0000FF，等 5 秒'
Write-Host '  4) 把【分区 4】设为静态纯白 FFFFFF，等 5 秒'
Write-Host '  5) 如果某个颜色预设里没有，直接用调色盘/连续滑动调过去（滑过的中间色也会被抓到，很有用）'
Write-Host '  6) 切一次【呼吸/彩虹】动画（全键盘），等 5 秒'
Write-Host '  7) 按 Fn+F9 调一档亮度，等 5 秒'
Write-Host ''
Write-Host '完成后按 Enter 停止抓包...' -ForegroundColor Yellow
Read-Host

# ---- 5. stop and report -----------------------------------------------------
foreach ($p in $procs) {
    if ($p -and -not $p.HasExited) {
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Write-Log "已停止抓包进程 PID=$($p.Id)"
    }
}
Start-Sleep -Seconds 2

Write-Host ''
Write-Host '抓包文件:'
$finalFiles = Get-ChildItem -Path $OutDir -File -ErrorAction SilentlyContinue |
    Sort-Object Length -Descending
foreach ($f in $finalFiles) {
    $size = if ($f.Name -like '*.pcap*') { '{0} KB' -f [math]::Round($f.Length / 1KB, 1) } else { '{0} B' -f $f.Length }
    Write-Host ("  {0}  ({1})" -f $f.Name, $size)
    Write-Log "文件: $($f.Name) $($f.Length) 字节"
}

$pcapFiles = $finalFiles | Where-Object { $_.Name -like '*.pcap*' -and $_.Length -gt 0 }
if ($pcapFiles.Count -eq 0) {
    Write-Log '错误: 没有产生任何非空抓包文件。'
    Write-Host '没有抓到数据。请把本目录的 capture.log 发给助手分析。' -ForegroundColor Red
} else {
    Set-Content -LiteralPath (Join-Path $OutDir 'DONE.txt') -Value "capture ok $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -Encoding UTF8
    Write-Host ''
    Write-Host "已保存到: $OutDir" -ForegroundColor Green
    Write-Host '请把整个 omen_capture 文件夹（含 capture.log）发给助手分析。'
}
