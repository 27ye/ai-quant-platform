<#!
Start a NEW loopback-only MySQL 8 acceptance instance. Never touches services or
existing data directories. Runtime secrets/data are retained under ignored frozen/.
#>
[CmdletBinding()]
param(
    [string]$MySqlBin = 'D:\Program Files\MySQL\MySQL Server 8.0\bin'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function New-PrivateDirectory([string]$Path) {
    if (Test-Path -LiteralPath $Path) { throw 'Runtime directory already exists; refusing reuse.' }
    $directory = New-Item -ItemType Directory -Path $Path
    $acl = Get-Acl -LiteralPath $directory.FullName
    $acl.SetAccessRuleProtection($true, $false)
    $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $inherit = [System.Security.AccessControl.InheritanceFlags]'ContainerInherit, ObjectInherit'
    $propagate = [System.Security.AccessControl.PropagationFlags]::None
    foreach ($identity in @($sid, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity, 'FullControl', $inherit, $propagate, 'Allow'
        )
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $directory.FullName -AclObject $acl
}

function New-LocalPassword {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    # Base64 contains no SQL quote, newline, or option-file escape characters.
    return 'Aa1!' + [Convert]::ToBase64String($bytes)
}

$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$mysqld = Join-Path $MySqlBin 'mysqld.exe'
$mysql = Join-Path $MySqlBin 'mysql.exe'
if (-not (Test-Path -LiteralPath $mysqld) -or -not (Test-Path -LiteralPath $mysql)) {
    throw 'MySQL server/client executables are unavailable.'
}
$versionText = & $mysqld --no-defaults --version
if ($LASTEXITCODE -ne 0 -or $versionText -notmatch 'Ver 8\.0\.' -or $versionText -match 'MariaDB') {
    throw 'Only a MySQL 8.0 executable is permitted.'
}

# Fail before creating files if the requested endpoint cannot be reserved.
$listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 3307)
$listener.Server.ExclusiveAddressUse = $true
try { $listener.Start() } catch { throw 'Port 3307 is occupied or unavailable; no service was stopped.' }
finally { $listener.Stop() }

$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $repo 'frozen\_runtime'))
$stamp = [DateTime]::UtcNow.ToString('yyyyMMdd_HHmmss_ffffff')
$runtime = [IO.Path]::GetFullPath((Join-Path $runtimeRoot "mysql_$stamp"))
if (-not $runtime.StartsWith($runtimeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Runtime path escaped its designated directory.'
}
& git -C $repo check-ignore --quiet --no-index 'frozen/_runtime/probe.env'
if ($LASTEXITCODE -ne 0) { throw 'Runtime directory must be Git-ignored before creating credentials.' }
New-PrivateDirectory $runtime

$dataDir = Join-Path $runtime 'data'
$baseDir = [IO.Path]::GetFullPath((Join-Path $MySqlBin '..')).Replace('\', '/')
$dataOption = $dataDir.Replace('\', '/')
$initError = Join-Path $runtime 'initialize.stderr.log'
$initOutput = Join-Path $runtime 'initialize.stdout.log'
$initialize = Start-Process -FilePath $mysqld -WindowStyle Hidden -PassThru -ArgumentList @(
    '--no-defaults', '--initialize', '--console', "--basedir=`"$baseDir`"", "--datadir=`"$dataOption`""
) -RedirectStandardError $initError -RedirectStandardOutput $initOutput
if (-not $initialize.WaitForExit(60000)) { throw 'Initialization still running; data retained. Inspect the private runtime directory.' }
if ($initialize.ExitCode -ne 0) { throw 'MySQL initialization failed; private logs and data retained.' }

$rootPassword = New-LocalPassword
$appPassword = New-LocalPassword
$bootstrapFile = Join-Path $runtime 'bootstrap.sql'
$clientFile = Join-Path $runtime 'client.cnf'
$envFile = Join-Path $runtime 'acceptance.env'
# The app account only has privileges on the generated acceptance DB namespace.
# Native password is limited to this loopback-only temporary instance: the
# existing PyMySQL environment has no optional RSA/cryptography dependency.
$bootstrap = @"
ALTER USER 'root'@'localhost' IDENTIFIED BY '$rootPassword';
CREATE USER 'acceptance'@'127.0.0.1' IDENTIFIED WITH mysql_native_password BY '$appPassword';
GRANT ALL PRIVILEGES ON ``ai\_quant\_v1\_acceptance\_%``.* TO 'acceptance'@'127.0.0.1';
"@
[IO.File]::WriteAllText($bootstrapFile, $bootstrap, [Text.Encoding]::ASCII)
[IO.File]::WriteAllText($clientFile, @"
[client]
host=127.0.0.1
port=3307
protocol=TCP
user=acceptance
password=$appPassword
"@, [Text.Encoding]::ASCII)
[IO.File]::WriteAllText($envFile, @"
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3307
MYSQL_USER=acceptance
MYSQL_PASSWORD=$appPassword
"@, [Text.Encoding]::ASCII)

$serverError = Join-Path $runtime 'server.stderr.log'
$serverOutput = Join-Path $runtime 'server.stdout.log'
$pidFile = Join-Path $runtime 'mysql.pid'
$server = Start-Process -FilePath $mysqld -WindowStyle Hidden -PassThru -ArgumentList @(
    '--no-defaults', '--console', "--basedir=`"$baseDir`"", "--datadir=`"$dataOption`"",
    '--bind-address=127.0.0.1', '--port=3307', '--mysqlx=OFF', '--skip-name-resolve',
    '--skip-log-bin', '--local-infile=OFF', '--secure-file-priv=NULL',
    "--pid-file=`"$($pidFile.Replace('\', '/'))`"",
    "--init-file=`"$($bootstrapFile.Replace('\', '/'))`""
) -RedirectStandardError $serverError -RedirectStandardOutput $serverOutput

$identity = ''
$clientError = Join-Path $runtime 'client.stderr.log'
$clientOutput = Join-Path $runtime 'client.stdout.log'
$clientExit = 1
$deadline = [DateTime]::UtcNow.AddSeconds(45)
while ([DateTime]::UtcNow -lt $deadline) {
    $server.Refresh()
    if ($server.HasExited) { throw 'Isolated MySQL exited; private logs/data retained.' }
    # Capture stdout/stderr: never print raw authentication errors or secrets.
    $probe = Start-Process -FilePath $mysql -WindowStyle Hidden -Wait -PassThru -ArgumentList @(
        "--defaults-file=`"$clientFile`"", '--batch', '--skip-column-names', '--connect-timeout=2',
        '--execute="SELECT VERSION(), @@port, @@datadir;"'
    ) -RedirectStandardError $clientError -RedirectStandardOutput $clientOutput
    $clientExit = $probe.ExitCode
    if ($clientExit -eq 0) {
        $identity = Get-Content -LiteralPath $clientOutput -Raw
        break
    }
    Start-Sleep -Milliseconds 400
}
if ($clientExit -ne 0 -or -not $identity) { throw 'Isolated MySQL readiness failed; private logs/data retained.' }
$fields = ([string]$identity).Trim().Split("`t")
if ($fields.Count -ne 3 -or $fields[0] -notmatch '^8\.0\.' -or $fields[1] -ne '3307') {
    throw 'Server identity check failed; refusing further work.'
}
if ([IO.Path]::GetFullPath($fields[2]).TrimEnd('\', '/') -ne $dataDir.TrimEnd('\', '/')) {
    throw 'Server data directory is not the newly initialized directory.'
}
$manifest = [ordered]@{
    runtime_directory = $runtime
    data_directory = $dataDir
    pid = $server.Id
    host = '127.0.0.1'
    port = 3307
    version = $fields[0]
    environment_file = $envFile
    client_options_file = $clientFile
    retained = $true
}
[IO.File]::WriteAllText((Join-Path $runtime 'instance.json'), ($manifest | ConvertTo-Json), [Text.Encoding]::UTF8)
$manifest | ConvertTo-Json -Compress
