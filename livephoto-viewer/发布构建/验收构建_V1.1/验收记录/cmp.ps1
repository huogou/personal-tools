param(
    [Parameter(Mandatory = $true)][string]$A,
    [Parameter(Mandatory = $true)][string]$B
)
$ja = (Get-Content -LiteralPath $A -Raw -Encoding UTF8) | ConvertFrom-Json
$jb = (Get-Content -LiteralPath $B -Raw -Encoding UTF8) | ConvertFrom-Json
$diff = @()
$ha = @{}; foreach ($f in $ja.Files) { $ha[$f.Rel] = $f }
$hb = @{}; foreach ($f in $jb.Files) { $hb[$f.Rel] = $f }
foreach ($k in $ha.Keys) {
    if (-not $hb.ContainsKey($k)) { $diff += "MISSING_IN_B: $k" }
    else {
        if ($ha[$k].Len -ne $hb[$k].Len) { $diff += "LEN_CHANGED: $k ($($ha[$k].Len) -> $($hb[$k].Len))" }
        if ($ha[$k].MTime -ne $hb[$k].MTime) { $diff += "MTIME_CHANGED: $k" }
        if ($ha[$k].Sha -ne $hb[$k].Sha) { $diff += "SHA_CHANGED: $k" }
    }
}
foreach ($k in $hb.Keys) { if (-not $ha.ContainsKey($k)) { $diff += "NEW_IN_B: $k" } }
$da = @($ja.Dirs); $db = @($jb.Dirs)
foreach ($d in $da) { if ($db -notcontains $d) { $diff += "DIR_MISSING_IN_B: $d" } }
foreach ($d in $db) { if ($da -notcontains $d) { $diff += "DIR_NEW_IN_B: $d" } }
if ($diff.Count -eq 0) { "IDENTICAL: files=$($ja.Files.Count) dirs=$($da.Count)" } else { $diff }
