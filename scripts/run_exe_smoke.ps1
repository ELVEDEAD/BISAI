$root = Split-Path $PSScriptRoot -Parent
$p = Start-Process -FilePath "$root\dist\Astrarium\Astrarium.exe" -PassThru
Start-Sleep -Seconds 12
if ($p.HasExited) {
    "LAUNCH_FAIL exit=$($p.ExitCode)"
} else {
    "LAUNCH_OK pid=$($p.Id)"
    Stop-Process -Id $p.Id -Force
}