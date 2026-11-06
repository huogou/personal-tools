param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [Parameter(Mandatory = $true)][string]$SrcDir,
    [Parameter(Mandatory = $true)][string]$Shot,
    [Parameter(Mandatory = $true)][string]$NamesFile,
    [Parameter(Mandatory = $true)][string]$OutLog,
    [int]$WaitSec = 25
)
# MSAA (oleacc) driven GUI acceptance for the frozen EXE.
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$cs = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class Msaa {
    [DllImport("oleacc.dll")]
    static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint dwId, ref Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out object ppvObject);
    public static object Root(IntPtr hwnd) {
        Guid iid = new Guid("618736E0-3C3D-11CF-810C-00AA00389B71");
        object o; int hr = AccessibleObjectFromWindow(hwnd, 0xFFFFFFFC, ref iid, out o);
        if (hr != 0 || o == null) return null;
        return o;
    }
    public static List<string> Dump(object acc, int depth, int maxDepth) {
        var res = new List<string>();
        try {
            dynamic a = acc;
            int n = 0;
            try { n = (int)a.accChildCount; } catch { }
            for (int i = 1; i <= n; i++) {
                object child = null; int id = i;
                try { child = a.accChild(i); } catch { }
                if (child != null && !(child is int)) id = 0;
                string name = "", role = "", val = "", action = "";
                try { name = a.accName(id); } catch { }
                try { role = "" + (a.accRole(id)); } catch { }
                try { val = a.accValue(id); } catch { }
                try { action = a.accDefaultAction(id); } catch { }
                res.Add(depth + "|" + id + "|" + role + "|" + name + "|" + val + "|" + action);
                if (child != null && !(child is int) && depth < maxDepth) {
                    res.AddRange(Dump(child, depth + 1, maxDepth));
                }
            }
        } catch (Exception e) { res.Add(depth + "|ERR|" + e.GetType().Name + "|" + e.Message + "||"); }
        return res;
    }
    public static bool DoDefault(object acc, int childId) {
        try { dynamic a = acc; a.accDoDefaultAction(childId); return true; } catch { return false; }
    }
    public static bool SetVal(object acc, int childId, string v) {
        try { dynamic a = acc; a.accValue[childId] = v; return true; } catch { return false; }
    }
    public static bool Select(object acc, int childId) {
        try { dynamic a = acc; a.accSelect(1, childId); return true; } catch { return false; }
    }
}
'@
Add-Type -TypeDefinition $cs -Language CSharp -ReferencedAssemblies @('System.dll', 'System.Core.dll', 'Microsoft.CSharp.dll')
$names = Get-Content -LiteralPath $NamesFile -Encoding UTF8
$previewBtn = $names[0]

$p = Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds 6
$uiProc = $null
$deadline = (Get-Date).AddSeconds($WaitSec)
while ((Get-Date) -lt $deadline) {
    $uiProc = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and $_.Path -eq $Exe } | Select-Object -First 1
    if ($uiProc) { break }
    Start-Sleep -Milliseconds 800
}
$lines = New-Object System.Collections.Generic.List[string]
if (-not $uiProc) { $lines.Add("RESULT=NO_WINDOW"); $lines | Set-Content $OutLog -Encoding UTF8; try { $p.Kill() } catch {}; exit 2 }
$lines.Add("UI_PID=$($uiProc.Id) TITLE=$($uiProc.MainWindowTitle)")
$root = [Msaa]::Root($uiProc.MainWindowHandle)
if (-not $root) { $lines.Add("RESULT=NO_MSAA_ROOT"); $lines | Set-Content $OutLog -Encoding UTF8; try { $p.Kill() } catch {}; exit 3 }
$dump = [Msaa]::Dump($root, 0, 6)
foreach ($l in $dump) { $lines.Add("TREE|$l") }

$entries = @(); $buttons = @()
foreach ($l in $dump) {
    $parts = $l -split '\|'
    if ($parts.Count -lt 6) { continue }
    $depth = $parts[0]; $id = $parts[1]; $role = $parts[2]; $name = $parts[3]
    if ($role -eq '42') { $entries += ,@($depth, $id, $name) }
    if ($role -eq '43') { $buttons += ,@($depth, $id, $name) }
}
$lines.Add("ENTRIES=$($entries.Count) BUTTONS=$($buttons.Count)")
foreach ($e in $entries) { $lines.Add("ENTRY|$($e[0])|$($e[1])|$($e[2])") }
foreach ($b in $buttons) { $lines.Add("BUTTON|$($b[0])|$($b[1])|$($b[2])") }

$setOk = $false
if ($entries.Count -ge 1) {
    $e0 = $entries[0]
    $setOk = [Msaa]::SetVal($root, [int]$e0[1], $SrcDir)
    if (-not $setOk) { [Msaa]::Select($root, [int]$e0[1]) | Out-Null }
    $lines.Add("SET_ENTRY_OK=$setOk")
}
Start-Sleep -Milliseconds 900

$target = $buttons | Where-Object { $_[2] -eq $previewBtn } | Select-Object -First 1
if (-not $target) { $lines.Add("RESULT=PREVIEW_BUTTON_NOT_FOUND") } else {
    $lines.Add("CLICK_NAME=$($target[2]) CHILDID=$($target[1])")
    $ok = [Msaa]::DoDefault($root, [int]$target[1])
    $lines.Add("DO_DEFAULT_ACTION=$ok")
}
Start-Sleep -Seconds 12

$dump2 = [Msaa]::Dump($root, 0, 6)
foreach ($l in $dump2) { $lines.Add("TREE2|$l") }

$bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
$lines.Add("SCREENSHOT=$Shot")
$lines | Set-Content -LiteralPath $OutLog -Encoding UTF8
Write-Output "DONE entries=$($entries.Count) buttons=$($buttons.Count) log=$OutLog"
try { $p.CloseMainWindow() | Out-Null } catch {}
Start-Sleep -Seconds 2
Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $Exe } | ForEach-Object { try { $_.Kill() } catch {} }
