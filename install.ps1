$ErrorActionPreference = 'Stop'
$repo = if ($env:AGENTBRIDGE_REPOSITORY) { $env:AGENTBRIDGE_REPOSITORY } else { 'guna81/agent-bridge' }
$base = if ($env:AGENTBRIDGE_RELEASE_BASE_URL) { $env:AGENTBRIDGE_RELEASE_BASE_URL } else { "https://github.com/$repo/releases/latest/download" }
if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne [System.Runtime.InteropServices.Architecture]::X64) { throw 'Only Windows x86-64 release packages are currently available.' }
$name = 'agentbridge-windows-x86_64.zip'
$work = Join-Path ([System.IO.Path]::GetTempPath()) ("agentbridge-install-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $work | Out-Null
try {
    $archive = Join-Path $work $name
    Invoke-WebRequest -Uri "$base/$name" -OutFile $archive
    $checksum = Join-Path $work "$name.sha256"
    Invoke-WebRequest -Uri "$base/$name.sha256" -OutFile $checksum
    $expected = ((Get-Content $checksum -Raw).Trim() -split '\s+')[0]
    if ($expected -notmatch '^[a-fA-F0-9]{64}$') { throw 'Invalid checksum file.' }
    if ((Get-FileHash -Algorithm SHA256 $archive).Hash -ne $expected) { throw 'Checksum verification failed.' }
    $unpack = Join-Path $work 'unpack'
    Expand-Archive -LiteralPath $archive -DestinationPath $unpack
    if (-not (Test-Path (Join-Path $unpack 'agentbridge\agentbridge.exe'))) { throw 'Invalid release archive.' }
    $root = if ($env:AGENTBRIDGE_INSTALL_ROOT) { $env:AGENTBRIDGE_INSTALL_ROOT } else { Join-Path $env:LOCALAPPDATA 'AgentBridge' }
    $bin = if ($env:AGENTBRIDGE_BIN_DIR) { $env:AGENTBRIDGE_BIN_DIR } else { Join-Path $root 'bin' }
    $release = Join-Path $root ("releases\release-" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Force -Path $release, $bin | Out-Null
    Move-Item -LiteralPath (Join-Path $unpack 'agentbridge') -Destination $release
    $launcher = Join-Path $bin 'agentbridge.cmd'
    if (Test-Path $launcher) {
        $backup = "$launcher.backup.$(Get-Date -Format yyyyMMddHHmmss)"
        Move-Item $launcher $backup
        Write-Host "Previous command saved as $backup"
    }
    $exe = Join-Path $release 'agentbridge\agentbridge.exe'
    [System.IO.File]::WriteAllText($launcher, "@echo off`r`nchcp 65001 >nul`r`n`"$exe`" %*`r`n", [System.Text.UTF8Encoding]::new($false))
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($null -eq $userPath) { $userPath = '' }
    if (($userPath -split ';') -notcontains $bin) {
        [Environment]::SetEnvironmentVariable('Path', (($userPath.TrimEnd(';') + ';' + $bin).TrimStart(';')), 'User')
    }
    Write-Host "Installed AgentBridge to $launcher. Open a new terminal to update PATH."
    Write-Host 'Run: agentbridge start'
    Write-Host 'Then: agentbridge dashboard'
} finally { Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue }
