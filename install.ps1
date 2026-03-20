# BrainJack Service — Windows Installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1
# Options: install.ps1 [-TLS] [-Uninstall]

param(
    [switch]$TLS,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "BrainJack Service"
$EnvFile = Join-Path $AgentDir ".env"
$EnvTemplate = Join-Path $AgentDir ".env.template"

function Write-Step($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Red }

# --- Uninstall ---
if ($Uninstall) {
    Write-Step "Uninstalling BrainJack Service..."
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Ok "Scheduled task removed."
    } else {
        Write-Warn "No scheduled task found."
    }
    # Remove startup VBS
    $startupVbs = Join-Path ([Environment]::GetFolderPath("Startup")) "brainjack.vbs"
    if (Test-Path $startupVbs) {
        Remove-Item $startupVbs -Force
        Write-Ok "Startup script removed."
    }
    # Stop any running agent
    Get-Process -Name "python*" -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*agent.py*"
    } | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Ok "Uninstall complete."
    exit 0
}

Write-Host ""
Write-Host "  ____            _         _            _    " -ForegroundColor Magenta
Write-Host " | __ ) _ __ __ _(_)_ __   | | __ _  ___| | __" -ForegroundColor Magenta
Write-Host " |  _ \| '__/ _`` | | '_ \  | |/ _`` |/ __| |/ /" -ForegroundColor Magenta
Write-Host " | |_) | | | (_| | | | | |_| | (_| | (__|   < " -ForegroundColor Magenta
Write-Host " |____/|_|  \__,_|_|_| |_\___/ \__,_|\___|_|\_\" -ForegroundColor Magenta
Write-Host ""
Write-Host "  Voice goes in, keystrokes come out." -ForegroundColor White
Write-Host ""

# --- Check Python ---
Write-Step "Checking Python..."
$python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3\.(\d+)") {
            $minor = [int]$Matches[1]
            if ($minor -ge 10) {
                $python = $cmd
                Write-Ok "Found $ver ($cmd)"
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Err "Python 3.10+ not found."
    Write-Host ""
    Write-Host "Install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "  - Check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    Write-Host "  - Then re-run this installer" -ForegroundColor Yellow
    Write-Host ""
    $openBrowser = Read-Host "Open Python download page? (y/n)"
    if ($openBrowser -eq "y") {
        Start-Process "https://www.python.org/downloads/"
    }
    exit 1
}

# --- Create venv ---
Write-Step "Creating virtual environment..."
$venvDir = Join-Path $AgentDir ".venv"
if (-not (Test-Path $venvDir)) {
    & $python -m venv $venvDir
}
$pip = Join-Path $venvDir "Scripts\pip.exe"
$pythonVenv = Join-Path $venvDir "Scripts\python.exe"

Write-Step "Installing dependencies..."
& $pip install -q -r (Join-Path $AgentDir "requirements.txt")
Write-Ok "Dependencies installed."

# --- .env setup ---
if (-not (Test-Path $EnvFile)) {
    Write-Step "Creating .env from template..."
    Copy-Item $EnvTemplate $EnvFile
}

# --- Token generation ---
$envContent = Get-Content $EnvFile -Raw
if ($envContent -match "BRAINJACK_TOKEN=\s*$" -or $envContent -match "BRAINJACK_TOKEN=$") {
    Write-Step "Generating auth token..."
    $token = & $pythonVenv -c "import secrets; print(secrets.token_urlsafe(32))"
    $envContent = $envContent -replace "BRAINJACK_TOKEN=.*", "BRAINJACK_TOKEN=$token"
    Set-Content $EnvFile $envContent -NoNewline
    Write-Host ""
    Write-Host "  ========================================" -ForegroundColor Green
    Write-Host "  AUTH TOKEN (copy to your BrainJack app):" -ForegroundColor Green
    Write-Host "  $token" -ForegroundColor White
    Write-Host "  ========================================" -ForegroundColor Green
    Write-Host ""
} else {
    $existingToken = [regex]::Match($envContent, "BRAINJACK_TOKEN=(.+)").Groups[1].Value.Trim()
    Write-Ok "Auth token already set."
    Write-Host ""
    Write-Host "  Your token: $existingToken" -ForegroundColor White
    Write-Host ""
}

# --- TLS self-signed cert ---
if ($TLS) {
    $certDir = Join-Path $AgentDir "certs"
    $certFile = Join-Path $certDir "brainjack.pem"
    $keyFile = Join-Path $certDir "brainjack-key.pem"

    if (-not (Test-Path $certFile)) {
        Write-Step "Generating self-signed TLS certificate..."
        New-Item -ItemType Directory -Path $certDir -Force | Out-Null

        $opensslPath = Get-Command openssl -ErrorAction SilentlyContinue
        if ($opensslPath) {
            $hostname = $env:COMPUTERNAME
            & openssl req -x509 -newkey rsa:2048 -nodes `
                -keyout $keyFile -out $certFile `
                -days 365 -subj "/CN=$hostname" `
                -addext "subjectAltName=DNS:$hostname,DNS:localhost,IP:127.0.0.1" 2>$null

            $envContent = Get-Content $EnvFile -Raw
            $envContent = $envContent -replace "BRAINJACK_TLS_CERT=.*", "BRAINJACK_TLS_CERT=$certFile"
            $envContent = $envContent -replace "BRAINJACK_TLS_KEY=.*", "BRAINJACK_TLS_KEY=$keyFile"
            Set-Content $EnvFile $envContent -NoNewline
            Write-Ok "TLS cert created: $certFile"
        } else {
            Write-Warn "OpenSSL not found. Install Git for Windows (includes OpenSSL) or skip TLS."
        }
    } else {
        Write-Ok "TLS cert already exists."
    }
}

# --- Windows Firewall rule ---
Write-Step "Configuring firewall..."
$fwRule = Get-NetFirewallRule -DisplayName "BrainJack Service" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    try {
        New-NetFirewallRule -DisplayName "BrainJack Service" `
            -Direction Inbound -Protocol TCP -LocalPort 9898 `
            -Action Allow -Profile Domain,Private,Public `
            -Description "Allow BrainJack Service WebSocket connections" | Out-Null
        Write-Ok "Firewall rule added (all network profiles)."
    } catch {
        Write-Warn "Could not add firewall rule. Run as Administrator, or manually allow port 9898."
    }
} else {
    # Ensure rule covers all profiles (not just Private)
    try {
        Set-NetFirewallRule -DisplayName "BrainJack Service" -Profile Domain,Private,Public
        Write-Ok "Firewall rule updated (all network profiles)."
    } catch {
        Write-Ok "Firewall rule already exists."
    }
}

# --- Auto-start via Startup folder ---
# Uses a VBS launcher in the Startup folder instead of Scheduled Task.
# Scheduled Tasks launched remotely (SSH/RDP) run on a detached desktop
# and cannot inject keystrokes. The Startup folder runs in the interactive
# desktop session, which is required for SendInput to work.
Write-Step "Setting up auto-start..."

# Remove any old Scheduled Task (doesn't work for SendInput)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok "Removed old scheduled task (replaced by startup script)."
}

# Create VBS launcher in Startup folder (runs hidden, no console window)
$startupDir = [Environment]::GetFolderPath("Startup")
$vbsPath = Join-Path $startupDir "brainjack.vbs"
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d $AgentDir && .venv\Scripts\pythonw.exe agent.py", 0, False
"@
Set-Content -Path $vbsPath -Value $vbsContent -Encoding ASCII
Write-Ok "Startup script created (runs hidden on login)."

# Also create a desktop shortcut for manual start
$desktopBat = Join-Path ([Environment]::GetFolderPath("Desktop")) "Start-BrainJack.bat"
$batContent = @"
@echo off
cd /d $AgentDir
echo Starting BrainJack Service...
start /B .venv\Scripts\pythonw.exe agent.py
echo BrainJack Service started on port 9898.
timeout /t 3 /nobreak >nul
"@
Set-Content -Path $desktopBat -Value $batContent -Encoding ASCII
Write-Ok "Desktop shortcut created (Start-BrainJack.bat)."

# --- Start the agent now ---
Write-Step "Starting BrainJack Service..."
$agentProc = Start-Process -FilePath $pythonVenv -ArgumentList "agent.py" `
    -WorkingDirectory $AgentDir -PassThru -WindowStyle Hidden
Start-Sleep -Seconds 2

$listening = Get-NetTCPConnection -LocalPort 9898 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    Write-Ok "Agent is running on port 9898!"
} else {
    Write-Warn "Agent may not have started. Double-click Start-BrainJack.bat on your Desktop."
}

# --- Summary ---
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  BrainJack Service installed successfully!" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Port:      9898" -ForegroundColor White
Write-Host "  Auto-start: On login" -ForegroundColor White
Write-Host "  Config:    $EnvFile" -ForegroundColor White
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "  1. Open the BrainJack app on your phone" -ForegroundColor White
Write-Host "  2. Add this computer (use your local IP + port 9898)" -ForegroundColor White
Write-Host "  3. Paste the auth token shown above" -ForegroundColor White
Write-Host "  4. Start talking — words appear on screen" -ForegroundColor White
Write-Host ""
Write-Host "  Commands:" -ForegroundColor Yellow
Write-Host "  Stop:          taskkill /F /IM pythonw.exe" -ForegroundColor Gray
Write-Host "  Start:         Double-click Start-BrainJack.bat on Desktop" -ForegroundColor Gray
Write-Host "  Uninstall:     .\install.ps1 -Uninstall" -ForegroundColor Gray
Write-Host ""
