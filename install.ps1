# install.ps1 — patent-search-engine 一鍵安裝腳本 (Windows)
# 用法：在 PowerShell 中執行  .\install.ps1
# 需求：Python 3.9+, pip, winget (Windows 11 內建)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  patent-search-engine  Installation Script"           -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""

# ─── 1. Python packages ────────────────────────────────────────────────────
Write-Host "[1/4] Installing Python packages..." -ForegroundColor Yellow
pip install -r "$ScriptDir\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] pip install failed. Ensure Python 3.9+ is installed." -ForegroundColor Red
    exit 1
}
Write-Host "  OK — Python packages installed." -ForegroundColor Green

# ─── 2. Playwright browser ────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Installing Playwright Chromium browser..." -ForegroundColor Yellow
playwright install chromium
if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARN] playwright install failed. Browser fallback won't work." -ForegroundColor DarkYellow
} else {
    Write-Host "  OK — Chromium installed." -ForegroundColor Green
}

# ─── 3. Tor ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Setting up Tor..." -ForegroundColor Yellow

$TorDir    = "$ScriptDir\tor"
$TorExe    = "$TorDir\tor.exe"
$TorrcFile = "$TorDir\torrc"

# Check if tor.exe already exists (previous install or manual placement)
if (Test-Path $TorExe) {
    Write-Host "  OK — tor.exe already present at $TorExe" -ForegroundColor Green
} else {
    # Try method A: winget (Windows 11 built-in)
    Write-Host "  Trying winget to install Tor Expert Bundle..." -ForegroundColor Gray
    $wingetAvail = $null
    try { $wingetAvail = (Get-Command winget -ErrorAction Stop).Source } catch {}

    $TorBrowserPath = $null
    if ($wingetAvail) {
        try {
            winget install TorProject.TorBrowser --accept-package-agreements --accept-source-agreements --silent
            # Tor Browser installs tor.exe at a predictable path
            $candidates = @(
                "$env:LOCALAPPDATA\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
                "$env:ProgramFiles\Tor Browser\Browser\TorBrowser\Tor\tor.exe",
                "$env:USERPROFILE\Desktop\Tor Browser\Browser\TorBrowser\Tor\tor.exe"
            )
            foreach ($c in $candidates) {
                if (Test-Path $c) { $TorBrowserPath = $c; break }
            }
        } catch {
            Write-Host "  winget install failed: $_" -ForegroundColor DarkYellow
        }
    }

    if ($TorBrowserPath) {
        # Copy tor.exe and required DLLs into local tor\ folder
        New-Item -ItemType Directory -Force -Path $TorDir | Out-Null
        $TorSrcDir = Split-Path $TorBrowserPath
        Copy-Item "$TorSrcDir\tor.exe"       $TorDir -Force
        Copy-Item "$TorSrcDir\*.dll"         $TorDir -Force -ErrorAction SilentlyContinue
        Copy-Item "$TorSrcDir\*.so"          $TorDir -Force -ErrorAction SilentlyContinue
        Write-Host "  OK — tor.exe copied from Tor Browser to $TorDir" -ForegroundColor Green
    } else {
        # Fallback: download Tor Expert Bundle directly
        Write-Host "  winget path not found. Downloading Tor Expert Bundle..." -ForegroundColor Gray
        New-Item -ItemType Directory -Force -Path $TorDir | Out-Null

        # Fetch latest version from Tor dist API
        try {
            $distJson = Invoke-RestMethod "https://aus1.torproject.org/torbrowser/update_3/release/downloads.json" -TimeoutSec 30
            # Expert bundle is under "win64" key (tgz)
            $ebUrl = $distJson.downloads.win64."tor-expert-bundle"
            if (-not $ebUrl) { throw "Could not parse expert bundle URL" }
        } catch {
            # Hard-coded fallback URL (update manually if expired)
            $ebUrl = "https://archive.torproject.org/tor-package-archive/torbrowser/14.0.9/tor-expert-bundle-windows-x86_64-14.0.3.tar.gz"
            Write-Host "  Using fallback URL: $ebUrl" -ForegroundColor DarkYellow
        }

        $TgzPath = "$env:TEMP\tor-expert-bundle.tar.gz"
        try {
            Invoke-WebRequest $ebUrl -OutFile $TgzPath -TimeoutSec 120
            # Extract using tar (built-in since Windows 10 1803)
            tar -xzf $TgzPath -C $TorDir --strip-components=1
            Write-Host "  OK — Tor Expert Bundle extracted to $TorDir" -ForegroundColor Green
            Remove-Item $TgzPath -Force
        } catch {
            Write-Host ""
            Write-Host "[WARN] Automatic Tor download failed: $_" -ForegroundColor DarkYellow
            Write-Host "  Manual steps:" -ForegroundColor DarkYellow
            Write-Host "  1. Download Expert Bundle from https://www.torproject.org/download/tor/" -ForegroundColor DarkYellow
            Write-Host "  2. Extract tor.exe and all DLLs into: $TorDir" -ForegroundColor DarkYellow
        }
    }
}

# Write torrc config (if tor.exe is present)
if (Test-Path $TorExe) {
    if (-not (Test-Path $TorrcFile)) {
        # Write ASCII (no BOM) — UTF-8 BOM breaks Tor's config parser
    $torrcContent = "SocksPort 9050`r`nControlPort 9051`r`nDataDirectory $TorDir\data`r`nLog notice stdout`r`n"
    [System.IO.File]::WriteAllText($TorrcFile, $torrcContent, [System.Text.Encoding]::ASCII)
        New-Item -ItemType Directory -Force -Path "$TorDir\data" | Out-Null
        Write-Host "  torrc written to $TorrcFile" -ForegroundColor Green
    } else {
        Write-Host "  torrc already exists — skipping." -ForegroundColor Gray
    }
} else {
    Write-Host "  [WARN] tor.exe not found. Run proxy_manager.py --install for retry." -ForegroundColor DarkYellow
}

# ─── 4. Environment check ─────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Verifying environment..." -ForegroundColor Yellow

$checks = @(
    @{ name = "requests";        cmd = "python -c `"import requests; print(requests.__version__)`"" },
    @{ name = "playwright";      cmd = "python -c `"import playwright; print('ok')`"" },
    @{ name = "stem (Tor ctrl)"; cmd = "python -c `"import stem; print(stem.__version__)`"" },
    @{ name = "anthropic";       cmd = "python -c `"import anthropic; print(anthropic.__version__)`"" },
    @{ name = "tor.exe";         cmd = "Test-Path '$TorExe'" }
)

foreach ($c in $checks) {
    try {
        if ($c.name -eq "tor.exe") {
            $ok = Test-Path $TorExe
            $val = if ($ok) { "found" } else { "MISSING" }
            $color = if ($ok) { "Green" } else { "DarkYellow" }
        } else {
            $val = Invoke-Expression $c.cmd 2>$null
            $color = "Green"
        }
        Write-Host "  [OK] $($c.name): $val" -ForegroundColor $color
    } catch {
        Write-Host "  [WARN] $($c.name): not available" -ForegroundColor DarkYellow
    }
}

Write-Host ""
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "  Installation complete!"                               -ForegroundColor Cyan
Write-Host ""
Write-Host "  Next steps:"
Write-Host "  - Set ANTHROPIC_API_KEY env var for LLM features"
Write-Host "  - Start Tor:  python scripts/proxy_manager.py --start"
Write-Host "  - Test Tor:   python scripts/proxy_manager.py --check"
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host ""
