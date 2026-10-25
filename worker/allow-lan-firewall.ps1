# Run once in an elevated PowerShell window. This creates a LAN-only inbound rule.
param([string]$NasIp = '')
$ErrorActionPreference = 'Stop'
$workerPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $workerPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this script in PowerShell as administrator to configure Windows Firewall.' }
$workerRemoteAddress = if ($NasIp) { $NasIp } else { 'LocalSubnet' }
$workerRuleName = 'Shengjian-GPU-LAN-18788'
if (Get-NetFirewallRule -Name $workerRuleName -ErrorAction SilentlyContinue) {
    Set-NetFirewallRule -Name $workerRuleName -Enabled True -Profile Any -Action Allow
    Get-NetFirewallRule -Name $workerRuleName | Get-NetFirewallAddressFilter | Set-NetFirewallAddressFilter -RemoteAddress $workerRemoteAddress
} else {
    New-NetFirewallRule -Name $workerRuleName -DisplayName 'Shengjian GPU worker (LAN)' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 18788 -RemoteAddress $workerRemoteAddress -Profile Any | Out-Null
}
Write-Output ('Allowed TCP 18788 from ' + $workerRemoteAddress + '. No public port forwarding is needed.')
