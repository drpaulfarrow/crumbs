#Requires -RunAsAdministrator
# Point Windows at the demo's DNS server (127.0.0.1), so the "Whole PC" lane covers every app.
# Saves your current DNS settings first; undo with system-dns-off.ps1.
# Start the demo before running this, or name lookups will fail until you do.
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$cache = Join-Path $root ".cache"
New-Item -ItemType Directory -Force $cache | Out-Null
$saveFile = Join-Path $cache "original-dns.json"
if (Test-Path $saveFile) {
    Write-Warning "Already switched (found $saveFile). Run system-dns-off.ps1 first."
    exit 1
}

$adapters = Get-NetAdapter | Where-Object Status -eq "Up"
$saved = foreach ($a in $adapters) {
    $v4 = (Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv4).ServerAddresses
    $v6 = (Get-DnsClientServerAddress -InterfaceIndex $a.ifIndex -AddressFamily IPv6).ServerAddresses
    $key = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces\$($a.InterfaceGuid)"
    $static = [bool](Get-ItemProperty $key -ErrorAction SilentlyContinue).NameServer
    [pscustomobject]@{
        ifIndex    = $a.ifIndex
        name       = $a.Name
        servers    = @($v4)
        servers_v6 = @($v6)
        static     = $static
    }
}
@{ adapters = @($saved) } | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $saveFile

foreach ($a in $adapters) {
    Set-DnsClientServerAddress -InterfaceIndex $a.ifIndex -ServerAddresses ("127.0.0.1", "::1")
    Write-Host "DNS for '$($a.Name)' -> 127.0.0.1 / ::1"
}
Clear-DnsClientCache
Write-Host "`nDone. Saved previous settings to $saveFile"
Write-Host "Note: Chrome/Edge 'Use secure DNS' bypasses system DNS; turn it off for this lane to see browser traffic."
