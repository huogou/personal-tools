param(
    [Parameter(Mandatory = $true)][string]$Path
)
# 生成目录快照：相对路径 / 长度 / 修改时间(UTC ticks) / SHA256
$root = (Resolve-Path -LiteralPath $Path).Path
$items = Get-ChildItem -LiteralPath $root -Recurse -Force -File | ForEach-Object {
    [PSCustomObject]@{
        Rel   = $_.FullName.Substring($root.Length).TrimStart('\')
        Len   = $_.Length
        MTime = $_.LastWriteTimeUtc.Ticks
        Sha   = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$dirs = Get-ChildItem -LiteralPath $root -Recurse -Force -Directory | ForEach-Object {
    $_.FullName.Substring($root.Length).TrimStart('\')
}
[PSCustomObject]@{ Root = $root; Files = @($items); Dirs = @($dirs) } | ConvertTo-Json -Depth 5
