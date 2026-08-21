param(
  [ValidateSet('chrome','edge','firefox')]
  [string]$Browser = 'chrome'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host '=== Bilibili Video Reader v3 Local Relay ===' -ForegroundColor Cyan
Write-Host "Browser cookies: $Browser"

$PythonCmd = $null
try {
  & py -3 --version *> $null
  if ($LASTEXITCODE -eq 0) { $PythonCmd = @('py','-3') }
} catch {}
if (-not $PythonCmd) {
  try {
    & python --version *> $null
    if ($LASTEXITCODE -eq 0) { $PythonCmd = @('python') }
  } catch {}
}
if (-not $PythonCmd) {
  Write-Host 'Python 3 was not found. Install Python 3 from python.org, enable Add Python to PATH, then run this script again.' -ForegroundColor Red
  Read-Host 'Press Enter to exit'
  exit 1
}

$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
if (-not (Test-Path $VenvPython)) {
  Write-Host 'Creating local Python environment...'
  if ($PythonCmd.Count -eq 2) { & $PythonCmd[0] $PythonCmd[1] -m venv $Venv }
  else { & $PythonCmd[0] -m venv $Venv }
}

Write-Host 'Installing/updating local dependencies...'
& $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $Root 'requirements.txt')

$Cloudflared = Join-Path $Root 'cloudflared.exe'
if (-not (Test-Path $Cloudflared)) {
  Write-Host 'Downloading Cloudflare Tunnel client...'
  Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile $Cloudflared
}

$Token = [Guid]::NewGuid().ToString('N')
$RelayOut = Join-Path $Root 'relay.out.log'
$RelayErr = Join-Path $Root 'relay.err.log'
$TunnelOut = Join-Path $Root 'tunnel.out.log'
$TunnelErr = Join-Path $Root 'tunnel.err.log'
Remove-Item $RelayOut,$RelayErr,$TunnelOut,$TunnelErr -Force -ErrorAction SilentlyContinue

Write-Host 'Starting local Bilibili extractor...'
$Relay = Start-Process -FilePath $VenvPython -ArgumentList @('server.py','--token',$Token,'--browser',$Browser,'--port','8765') -WorkingDirectory $Root -RedirectStandardOutput $RelayOut -RedirectStandardError $RelayErr -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2
if ($Relay.HasExited) {
  Write-Host 'Local relay failed to start:' -ForegroundColor Red
  if (Test-Path $RelayErr) { Get-Content $RelayErr }
  Read-Host 'Press Enter to exit'
  exit 1
}

Write-Host 'Opening temporary Cloudflare Tunnel...'
$Tunnel = Start-Process -FilePath $Cloudflared -ArgumentList @('tunnel','--url','http://127.0.0.1:8765','--no-autoupdate') -WorkingDirectory $Root -RedirectStandardOutput $TunnelOut -RedirectStandardError $TunnelErr -PassThru -WindowStyle Hidden

$TunnelUrl = $null
for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Milliseconds 750
  $combined = ''
  if (Test-Path $TunnelOut) { $combined += (Get-Content $TunnelOut -Raw -ErrorAction SilentlyContinue) }
  if (Test-Path $TunnelErr) { $combined += (Get-Content $TunnelErr -Raw -ErrorAction SilentlyContinue) }
  $match = [regex]::Match($combined, 'https://[a-z0-9-]+\.trycloudflare\.com')
  if ($match.Success) {
    $TunnelUrl = $match.Value
    break
  }
  if ($Tunnel.HasExited) { break }
}

if (-not $TunnelUrl) {
  Write-Host 'Could not obtain a Quick Tunnel URL.' -ForegroundColor Red
  if (Test-Path $TunnelErr) { Get-Content $TunnelErr }
  try { Stop-Process -Id $Relay.Id -Force } catch {}
  Read-Host 'Press Enter to exit'
  exit 1
}

$FullRelayUrl = "$TunnelUrl/r/$Token"
try { Set-Clipboard -Value $FullRelayUrl } catch {}

Write-Host ''
Write-Host 'LOCAL RELAY IS READY' -ForegroundColor Green
Write-Host 'Keep this window open while using Bilibili Video Reader.' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Copy this value into Cloudflare Worker variable LOCAL_RELAY_URL:' -ForegroundColor Cyan
Write-Host $FullRelayUrl -ForegroundColor White
Write-Host ''
Write-Host '(It has also been copied to your clipboard when possible.)'
Write-Host "If Chrome cookie reading fails later, close Chrome completely and rerun, or use: .\start-local-relay.ps1 -Browser edge"
Write-Host ''
Read-Host 'Press Enter ONLY when you want to stop the relay'

try { Stop-Process -Id $Tunnel.Id -Force } catch {}
try { Stop-Process -Id $Relay.Id -Force } catch {}
Write-Host 'Relay stopped.'
