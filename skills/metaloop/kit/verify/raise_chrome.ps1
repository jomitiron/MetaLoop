param([string]$Profile, [int]$Port = 9333, [string]$TabUrlContains = "")
# Brings the RUN's Chrome window to the front (maximised) and, if asked, activates the tab whose URL contains the text.
# Use it when a pause needs the owner in that window: they otherwise reach for their own browser.
#   powershell -File raise_chrome.ps1 -Profile "C:\w\run\chrome-profile" -Port 9333 -TabUrlContains "intuit.com"
if ($TabUrlContains) {
    try {
        $tabs = (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json").Content | ConvertFrom-Json
        $tab = $tabs | Where-Object { $_.type -eq 'page' -and $_.url -like "*$TabUrlContains*" } | Select-Object -First 1
        if ($tab) { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/json/activate/$($tab.id)" | Out-Null }
    } catch {}
}
Add-Type @"
using System; using System.Runtime.InteropServices;
public class LoopWin { [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h); [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c); }
"@
$p = Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" | Where-Object { $_.CommandLine -like "*$Profile*" -and $_.CommandLine -notlike '*--type=*' } | Select-Object -First 1
if (-not $p) { "the run's Chrome is not running"; exit 1 }
$proc = Get-Process -Id $p.ProcessId
[LoopWin]::ShowWindow($proc.MainWindowHandle, 9) | Out-Null
[LoopWin]::ShowWindow($proc.MainWindowHandle, 3) | Out-Null
[LoopWin]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
"raised: $($proc.MainWindowTitle)"
