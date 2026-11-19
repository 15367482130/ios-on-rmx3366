# driver_winusb.ps1 - best-effort: bind the phone (USB\VID_18D1*) to Microsoft's WinUSB.
#
# Why it is only best-effort: Windows has no generic "any device" WinUSB INF that we may
# install without writing one, and libwdi/Zadig is the tool that does it properly.  So this
# script tries, in order:
#   1. pnputil /add-driver on the Microsoft winusb.inf that ships in the DriverStore
#   2. a disable/enable toggle so the new driver is picked up
# and then reports what the device is actually bound to.  If it changed nothing, use Zadig:
# Options - List All Devices - pick the 18d1 device - select WinUSB - Replace Driver.
#
# Needs administrator (the batch script already runs elevated).

$ErrorActionPreference = 'Continue'
function Say($s) { Write-Host $s }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Say "[!] not administrator"; exit 3 }

$devices = Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue |
    Where-Object { $_.InstanceId -like 'USB\VID_18D1*' }
if (-not $devices) { Say "[!] no 18d1 device present - enter fastboot first"; exit 4 }

foreach ($d in $devices) {
    $inf = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_DriverInfPath' -ErrorAction SilentlyContinue).Data
    $svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data
    Say ("[i] {0}  status={1}  inf={2}  service={3}" -f $d.InstanceId, $d.Status, $inf, $svc)
}

$winusbDir = Get-ChildItem "C:\Windows\System32\DriverStore\FileRepository" -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like 'winusb.inf_amd64*' } | Select-Object -First 1
if (-not $winusbDir) { Say "[!] Microsoft winusb.inf not found in the DriverStore"; exit 5 }
$winusbInf = Join-Path $winusbDir.FullName 'winusb.inf'
Say "[+] Microsoft WinUSB: $winusbInf"

Say "[+] pnputil /add-driver ... /install"
pnputil /add-driver "$winusbInf" /install 2>&1 | ForEach-Object { Say "    $_" }

foreach ($d in $devices) {
    Say "[+] toggling $($d.InstanceId)"
    pnputil /disable-device "$($d.InstanceId)" 2>&1 | ForEach-Object { Say "    $_" }
    Start-Sleep -Seconds 2
    pnputil /enable-device "$($d.InstanceId)" 2>&1 | ForEach-Object { Say "    $_" }
    Start-Sleep -Seconds 4
}

foreach ($d in $devices) {
    $inf = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_DriverInfPath' -ErrorAction SilentlyContinue).Data
    $svc = (Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName 'DEVPKEY_Device_Service' -ErrorAction SilentlyContinue).Data
    Say ("[i] now: inf={0}  service={1}" -f $inf, $svc)
}

Say "[+] done. If 'service' is not WinUSB/libusbK, use Zadig (Options - List All Devices) instead."
