$root = Split-Path $PSScriptRoot -Parent
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "$root\installer.iss" > "$root\_iss.log" 2>&1
"ISCC_EXIT=$LASTEXITCODE"
Get-ChildItem "D:\比赛文件\Astrarium_Release" | Sort-Object LastWriteTime -Descending |
    Select-Object -First 3 Name, Length, LastWriteTime | Format-Table -AutoSize | Out-String