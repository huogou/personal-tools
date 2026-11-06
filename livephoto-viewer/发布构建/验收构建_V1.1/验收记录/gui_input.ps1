param([string]$Exe,[string]$SrcDir,[string]$ShotBefore,[string]$ShotAfter,[string]$OutLog,[int]$WaitSec=40)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$cs=@'
using System; using System.Runtime.InteropServices;
public static class W32 {
 [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
 [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
 [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
 [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
 [DllImport("user32.dll")] public static extern void mouse_event(uint f,uint dx,uint dy,uint d,IntPtr e);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int c);
 [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h,IntPtr a,int x,int y,int cx,int cy,uint f);
 public static void Topmost(IntPtr h){ SetWindowPos(h,new IntPtr(-1),0,0,0,0,0x0003); }
 public static void Notopmost(IntPtr h){ SetWindowPos(h,new IntPtr(-2),0,0,0,0,0x0003); }
 public static void Click(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(250);
  mouse_event(0x0002,0,0,0,IntPtr.Zero); System.Threading.Thread.Sleep(70); mouse_event(0x0004,0,0,0,IntPtr.Zero); }
}
'@
Add-Type -TypeDefinition $cs -ReferencedAssemblies @('System.dll','System.Core.dll')
$L=New-Object System.Collections.Generic.List[string]
function Shot { $b=[System.Windows.Forms.SystemInformation]::VirtualScreen
 $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height
 $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size); $g.Dispose(); $bmp }
$p=Start-Process -FilePath $Exe -PassThru
Start-Sleep -Seconds 6
$up=$null; $dl=(Get-Date).AddSeconds($WaitSec)
while((Get-Date) -lt $dl){ $up=Get-Process -EA SilentlyContinue|Where-Object{$_.MainWindowHandle -ne 0 -and $_.Path -eq $Exe}|Select-Object -First 1
 if($up){break}; Start-Sleep -Milliseconds 800 }
if(-not $up){ $L.Add('RESULT=NO_WINDOW'); $L|Set-Content $OutLog -Encoding UTF8; try{$p.Kill()}catch{}; exit 2 }
$hw=$up.MainWindowHandle
$L.Add("UI_PID=$($up.Id) TITLE=$($up.MainWindowTitle) HWND=$hw")
$r=New-Object W32+RECT; [W32]::GetWindowRect($hw,[ref]$r)|Out-Null
$L.Add("WINDOW_RECT=$($r.Left),$($r.Top),$($r.Right),$($r.Bottom)")
[W32]::ShowWindow($hw,9)|Out-Null; [W32]::SetForegroundWindow($hw)|Out-Null
[W32]::Topmost($hw)
Start-Sleep -Milliseconds 900
Start-Sleep -Seconds 2
$bmp=Shot; $bmp.Save($ShotBefore,[System.Drawing.Imaging.ImageFormat]::Png)
$vs=[System.Windows.Forms.SystemInformation]::VirtualScreen
$ox=$vs.X; $oy=$vs.Y
$L.Add("VS_ORIGIN=$ox,$oy SIZE=$($vs.Width)x$($vs.Height)")
$wx0=$r.Left-$ox; $wx1=$r.Right-$ox; $wy0=$r.Top-$oy; $wy1=$r.Bottom-$oy
$mX=99999;$mA=-1;$mY=99999;$mB=-1
for($y=$wy0;$y -lt $wy1;$y++){
 for($x=$wx0;$x -lt $wx1;$x++){
  $c=$bmp.GetPixel($x,$y)
  if([math]::Abs($c.R-31) -le 14 -and [math]::Abs($c.G-157) -le 14 -and [math]::Abs($c.B-85) -le 14){
   if($x -lt $mX){$mX=$x}; if($x -gt $mA){$mA=$x}; if($y -lt $mY){$mY=$y}; if($y -gt $mB){$mB=$y} } } }
$L.Add("GREEN_BOX=$mX,$mY,$mA,$mB")
if($mA -lt $mX){ $L.Add('RESULT=GREEN_NOT_FOUND'); $bmp.Dispose(); $L|Set-Content $OutLog -Encoding UTF8; try{$p.Kill()}catch{}; exit 3 }
$bx=[int](($mX+$mA)/2); $by=[int](($mY+$mB)/2)
$best=0;$ex=-1;$ey=-1
for($y=$wy0+10;$y -lt $mY-5;$y++){
 $rs=-1
 for($x=$wx0+5;$x -lt $wx1-5;$x++){
  $c=$bmp.GetPixel($x,$y)
  $w=($c.R -ge 246 -and $c.G -ge 246 -and $c.B -ge 246)
  if($w -and $rs -lt 0){$rs=$x}
  if(((-not $w) -or $x -eq $r.Right-6) -and $rs -ge 0){
   $len=$x-$rs
   if($len -gt $best){$best=$len;$ex=$rs+[int]($len/2);$ey=$y}
   $rs=-1 } } }
$L.Add("WHITE_ENTRY_X=$ex Y=$ey LEN=$best")
if($best -lt 80){ $L.Add('RESULT=ENTRY_NOT_FOUND'); $bmp.Dispose(); $L|Set-Content $OutLog -Encoding UTF8; try{$p.Kill()}catch{}; exit 4 }
Set-Clipboard -Value $SrcDir
Start-Sleep -Milliseconds 500
[W32]::SetForegroundWindow($hw)|Out-Null
[W32]::Click($ex+$ox,$ey+$oy)
Start-Sleep -Milliseconds 800
[System.Windows.Forms.SendKeys]::SendWait("^a")
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait("^v")
Start-Sleep -Milliseconds 1000
$L.Add("PASTE_DONE=$SrcDir")
[W32]::SetForegroundWindow($hw)|Out-Null
[W32]::Click($bx+$ox,$by+$oy)
$L.Add("CLICKED_GREEN=$bx,$by")
Start-Sleep -Seconds 14
$bmp2=Shot; $bmp2.Save($ShotAfter,[System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose(); $bmp2.Dispose()
$mk=@(Get-ChildItem $env:TEMP -Directory -Filter 'livephoto_preview_*' -EA SilentlyContinue|Where-Object{Test-Path (Join-Path $_.FullName '.livephoto_preview_owner')})
$L.Add("MARKED_PREVIEW_DIRS=$($mk.Count)")
foreach($m in $mk){ $L.Add("PREVIEW_DIR=$($m.FullName) FILES=$(@(Get-ChildItem $m.FullName -Recurse -File).Count) MTIME=$($m.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))") }
$L.Add("BROWSER_PROCS=$(@(Get-Process chrome,msedge -EA SilentlyContinue).Count)")
$L.Add('RESULT=DONE')
$L|Set-Content $OutLog -Encoding UTF8
Write-Output "DONE green=$bx,$by entry=$ex,$ey marked=$($mk.Count)"
[W32]::Notopmost($hw)
Start-Sleep -Seconds 1
Get-Process -EA SilentlyContinue|Where-Object{$_.Path -eq $Exe}|ForEach-Object{try{$_.Kill()}catch{}}
