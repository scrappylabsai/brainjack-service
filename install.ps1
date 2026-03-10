# BrainJack Agent — Windows Installer
# Run: powershell -ExecutionPolicy Bypass -File install.ps1
# Options: install.ps1 [-TLS] [-Uninstall]

param(
    [switch]$TLS,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$AgentDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$TaskName = "BrainJack Agent"
$EnvFile = Join-Path $AgentDir ".env"
$EnvTemplate = Join-Path $AgentDir ".env.template"

function Write-Step($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Cyan }
function Write-Ok($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Yellow }
function Write-Err($msg) { Write-Host "[brainjack] $msg" -ForegroundColor Red }

# --- Uninstall ---
if ($Uninstall) {
    Write-Step "Uninstalling BrainJack Agent..."
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Ok "Scheduled task removed."
    } else {
        Write-Warn "No scheduled task found."
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
$fwRule = Get-NetFirewallRule -DisplayName "BrainJack Agent" -ErrorAction SilentlyContinue
if (-not $fwRule) {
    try {
        New-NetFirewallRule -DisplayName "BrainJack Agent" `
            -Direction Inbound -Protocol TCP -LocalPort 9898 `
            -Action Allow -Profile Private `
            -Description "Allow BrainJack Agent WebSocket connections on private networks" | Out-Null
        Write-Ok "Firewall rule added (private networks only)."
    } catch {
        Write-Warn "Could not add firewall rule. Run as Administrator, or manually allow port 9898."
    }
} else {
    Write-Ok "Firewall rule already exists."
}

# --- Scheduled Task (auto-start on login) ---
Write-Step "Setting up auto-start..."
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute $pythonVenv `
    -Argument "agent.py" `
    -WorkingDirectory $AgentDir

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Seconds 30) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "BrainJack Agent — WebSocket HID injection service" | Out-Null

Write-Ok "Scheduled task created (starts on login)."

# --- Start the agent now ---
Write-Step "Starting BrainJack Agent..."
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

# Check if it's running
$running = Get-ScheduledTask -TaskName $TaskName
if ($running.State -eq "Running") {
    Write-Ok "Agent is running on port 9898!"
} else {
    Write-Warn "Agent may not have started. Check: Get-ScheduledTask -TaskName 'BrainJack Agent'"
}

# --- Summary ---
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  BrainJack Agent installed successfully!" -ForegroundColor Green
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
Write-Host "  Check status:  Get-ScheduledTask -TaskName 'BrainJack Agent'" -ForegroundColor Gray
Write-Host "  Stop:          Stop-ScheduledTask -TaskName 'BrainJack Agent'" -ForegroundColor Gray
Write-Host "  Start:         Start-ScheduledTask -TaskName 'BrainJack Agent'" -ForegroundColor Gray
Write-Host "  Uninstall:     .\install.ps1 -Uninstall" -ForegroundColor Gray
Write-Host ""
