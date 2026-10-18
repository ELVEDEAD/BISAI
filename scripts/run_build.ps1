$root = Split-Path $PSScriptRoot -Parent
$out = "$root\_build_out.txt"
$err = "$root\_build_err.txt"
Set-Location $root
python -m PyInstaller Astrarium.spec --noconfirm > $out 2> $err
"EXIT=$LASTEXITCODE" | Out-File -Append $out