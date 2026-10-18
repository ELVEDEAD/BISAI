$ErrorActionPreference = 'Stop'
$out = "$PSScriptRoot\..\_smoke_out.txt"
$err = "$PSScriptRoot\..\_smoke_err.txt"
python -m pytest tests -q --tb=short > $out 2> $err
"EXIT=$LASTEXITCODE" | Out-File -Append $out