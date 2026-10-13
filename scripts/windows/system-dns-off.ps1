#Requires -RunAsAdministrator
# Restore the DNS settings saved by system-dns-on.ps1.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$saveFile = Join-Path $root ".cache\original-dns.json"
if (-not (Test-Path $saveFile)) {
    Write-Warning "No saved settings found; resetting all connected adapters to automatic (DHCP) DNS."
    Get-NetAdapter | Where-Object Status -eq "Up" | ForEach-Object {
        Set-DnsClientServerAddress -InterfaceIndex $_.ifIndex -ResetServerAddresses
    }
    Clear-DnsClientCache
    exit 0
}

$saved = Get-Content $saveFile -Raw | ConvertFrom-Json
foreach ($a in $saved.adapters) {
    $servers = @($a.servers) + @($a.servers_v6) | Where-Object { $_ }
    if ($a.static -and $servers.Count -gt 0) {
        Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ServerAddresses $servers
        Write-Host "Restored '$($a.name)' -> $($servers -join ', ')"
    } else {
        Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ResetServerAddresses
        Write-Host "Restored '$($a.name)' -> automatic (DHCP)"
    }
}
Remove-Item $saveFile
Clear-DnsClientCache
Write-Host "Done."
