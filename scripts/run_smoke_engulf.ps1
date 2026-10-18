$ErrorActionPreference = 'Stop'
$out = "$PSScriptRoot\..\_smoke_out.txt"
$err = "$PSScriptRoot\..\_smoke_err.txt"
python -X utf8 "$PSScriptRoot\smoke_engulf.py" > $out 2> $err
"EXIT=$LASTEXITCODE" | Out-File -Append $out