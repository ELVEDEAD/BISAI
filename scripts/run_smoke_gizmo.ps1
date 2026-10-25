$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$p = Start-Process python -ArgumentList "-X","utf8","scripts\smoke_view_gizmo.py" `
    -WorkingDirectory $root `
    -RedirectStandardOutput "$root\_gizmo_out.txt" `
    -RedirectStandardError "$root\_gizmo_err.txt" `
    -PassThru -NoNewWindow
if (-not $p.WaitForExit(180000)) {
    $p.Kill()
    "TIMEOUT"
} else {
    "EXIT=$($p.ExitCode)"
}
Get-Content "$root\_gizmo_out.txt"
Get-Content "$root\_gizmo_err.txt" | Select-Object -First 8