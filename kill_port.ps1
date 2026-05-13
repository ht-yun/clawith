$connections = Get-NetTCPConnection -LocalPort 8009 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $connections) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "Killed PID $($conn.OwningProcess)"
}
