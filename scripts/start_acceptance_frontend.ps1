<# Start A's unmodified frontend with explicit real-API settings for this process. #>
[CmdletBinding()]
param(
    [ValidateSet('live', 'frozen')][string]$Mode = 'live',
    [ValidateRange(1024, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1024, 65535)][int]$Port = 5173
)
$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$response = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/v1/health" -UseBasicParsing -TimeoutSec 5
if ($response.Headers['X-Acceptance-Mode'] -ne $Mode) {
    throw 'Backend acceptance mode does not match. Start the acceptance backend first.'
}
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, $Port)
$listener.Server.ExclusiveAddressUse = $true
try { $listener.Start() } catch { throw "Port $Port is occupied; no existing process was stopped." }
finally { $listener.Stop() }

$values = @{
    VITE_API_BASE_URL = '/api/v1'
    VITE_PROXY_TARGET = "http://127.0.0.1:$BackendPort"
    VITE_USE_MOCK = 'false'
    VITE_ACCEPTANCE_MODE = $Mode
    VITE_ACCEPTANCE_START = [string]$response.Headers['X-Acceptance-Start']
    VITE_ACCEPTANCE_END = [string]$response.Headers['X-Acceptance-End']
}
foreach ($name in @('SEARCH', 'KLINE', 'INDICATORS', 'SCORE', 'BACKTEST', 'AI', 'NEWS')) {
    $values["VITE_USE_MOCK_$name"] = 'false'
}
Get-ChildItem Env: | Where-Object { $_.Name -like 'VITE_USE_MOCK_*' } | ForEach-Object {
    $values[$_.Name] = 'false'
}
$previous = @{}
foreach ($name in $values.Keys) {
    $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    [Environment]::SetEnvironmentVariable($name, $values[$name], 'Process')
}
Push-Location (Join-Path $repo 'frontend')
try {
    Write-Output "Acceptance frontend: mode=$Mode; mock=false; api=/api/v1; url=http://127.0.0.1:$Port"
    & npm.cmd run dev -- --host 127.0.0.1 --port $Port --strictPort
    if ($LASTEXITCODE -ne 0) { throw 'Frontend server exited unsuccessfully.' }
} finally {
    Pop-Location
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
}
