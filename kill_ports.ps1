Get-NetTCPConnection -LocalPort 8008,8009 -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $($_.OwningProcess) on port $($_.LocalPort)"
}
Write-Host "Done"
