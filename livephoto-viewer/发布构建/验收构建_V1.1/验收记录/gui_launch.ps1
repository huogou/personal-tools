param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$Shot,
    [int]$WaitSec = 8
)
# Launch GUI EXE, capture main window title + screenshot, then close
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$before = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Exe }).Count
$p = Start-Process -FilePath $Exe -PassThru
Write-Output "STARTED PID=$($p.Id) SAME_NAME_PROCS_BEFORE=$before"
$deadline = (Get-Date).AddSeconds($WaitSec)
$title = ''
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 700
    try { $p.Refresh() } catch { break }
    if ($p.HasExited) { Write-Output "EXITED_EARLY ExitCode=$($p.ExitCode)"; break }
    if ($p.MainWindowTitle) { $title = $p.MainWindowTitle; break }
}
Write-Output "MAIN_WINDOW_TITLE='$title'"
Write-Output "HAS_EXITED=$($p.HasExited)"
try { Write-Output "WORKING_SET_MB=$([math]::Round($p.WorkingSet64/1MB,1))" } catch {}
$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "SCREENSHOT=$Shot"
Start-Sleep -Milliseconds 400
try { $p.CloseMainWindow() | Out-Null } catch {}
Start-Sleep -Seconds 2
if (-not $p.HasExited) { try { $p.Kill() } catch {} ; Write-Output "FORCE_KILLED" } else { Write-Output "CLOSED_NORMALLY ExitCode=$($p.ExitCode)" }
