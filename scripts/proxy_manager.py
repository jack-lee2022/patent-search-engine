#!/usr/bin/env python3
"""
ProxyManager — patent-search-engine Tor proxy manager.

Manages Tor proxy, circuit rotation, and health checks.
Supports Windows (tor.exe in local tor\\ folder) and Linux (system tor).

Usage:
    python proxy_manager.py --check          # Is Tor running?
    python proxy_manager.py --start          # Start tor.exe (Windows)
    python proxy_manager.py --rotate         # Rotate circuit (NEWNYM)
    python proxy_manager.py --test           # Test Google Patents connectivity
    python proxy_manager.py --install        # Install Tor (Windows/Linux)
"""

import argparse
import os
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import requests

TOR_PROXY = "socks5://127.0.0.1:9050"
TOR_SOCKS_PORT = 9050
TOR_CONTROL_PORT = 9051
TOR_CONTROL_PASSWORD = ""

# Local tor.exe path (placed by install.ps1)
_SCRIPT_DIR = Path(__file__).parent
_REPO_ROOT  = _SCRIPT_DIR.parent
_LOCAL_TOR_EXE  = _REPO_ROOT / "tor" / "tor.exe"
_LOCAL_TORRC    = _REPO_ROOT / "tor" / "torrc"
_LOCAL_TOR_DATA = _REPO_ROOT / "tor" / "data"

# tor.exe process handle (kept alive for the session)
_tor_process: Optional[subprocess.Popen] = None


def _find_tor_exe() -> Optional[Path]:
    """Return path to tor.exe on Windows, or None."""
    if _LOCAL_TOR_EXE.exists():
        return _LOCAL_TOR_EXE
    # Tor Browser installed via winget
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
        Path(os.environ.get("USERPROFILE", "")) / "Desktop" / "Tor Browser" / "Browser" / "TorBrowser" / "Tor" / "tor.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


class ProxyManager:
    """Manage proxy connections for patent scraping."""

    def __init__(self, proxy_url: str = TOR_PROXY):
        self.proxy_url = proxy_url
        self.session = requests.Session()
        self.session.proxies = {"http": proxy_url, "https": proxy_url}

    def check_tor(self) -> bool:
        """Check if Tor is working."""
        try:
            resp = self.session.get(
                "https://check.torproject.org",
                timeout=30,
            )
            return "Congratulations" in resp.text or "Tor" in resp.text
        except requests.RequestException:
            return False

    def get_exit_ip(self) -> Optional[str]:
        """Get current exit IP through Tor."""
        try:
            resp = self.session.get("https://api.ipify.org", timeout=30)
            return resp.text.strip()
        except requests.RequestException:
            return None

    def rotate_tor_circuit(self) -> bool:
        """Send NEWNYM signal to Tor to rotate circuit."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(5)
                s.connect(("127.0.0.1", TOR_CONTROL_PORT))
                if TOR_CONTROL_PASSWORD:
                    s.sendall(f'AUTHENTICATE "{TOR_CONTROL_PASSWORD}"\r\n'.encode())
                s.sendall(b"SIGNAL NEWNYM\r\n")
                response = s.recv(1024).decode()
                return "OK" in response
        except Exception as e:
            print(f"[TOR ROTATE ERROR] {e}")
            return False

    def test_google_patents(self) -> dict:
        """Test Google Patents connectivity."""
        results = {
            "direct_ip": None,
            "tor_ip": None,
            "xhr_status": None,
            "detail_status": None,
            "cdn_status": None,
        }

        # Direct IP
        try:
            resp = requests.get("https://api.ipify.org", timeout=10)
            results["direct_ip"] = resp.text.strip()
        except Exception as e:
            results["direct_ip"] = f"error: {e}"

        # Tor IP
        try:
            resp = self.session.get("https://api.ipify.org", timeout=10)
            results["tor_ip"] = resp.text.strip()
        except Exception as e:
            results["tor_ip"] = f"error: {e}"

        # XHR API
        try:
            resp = self.session.get(
                "https://patents.google.com/xhr/query?url=q%3Dtest",
                timeout=30,
            )
            results["xhr_status"] = resp.status_code
        except Exception as e:
            results["xhr_status"] = f"error: {e}"

        # Detail page
        try:
            resp = self.session.get(
                "https://patents.google.com/patent/US11311692B2/en",
                timeout=30,
            )
            results["detail_status"] = resp.status_code
        except Exception as e:
            results["detail_status"] = f"error: {e}"

        # CDN
        try:
            resp = requests.get(
                "https://patentimages.storage.googleapis.com/",
                timeout=10,
            )
            results["cdn_status"] = resp.status_code
        except Exception as e:
            results["cdn_status"] = f"error: {e}"

        return results

    def start_tor_windows(self) -> bool:
        """Launch local tor.exe in background (Windows only)."""
        global _tor_process
        if _tor_process and _tor_process.poll() is None:
            print("[TOR] tor.exe already running.")
            return True

        tor_exe = _find_tor_exe()
        if not tor_exe:
            print("[TOR] tor.exe not found. Run: python proxy_manager.py --install")
            return False

        # Ensure data directory exists
        _LOCAL_TOR_DATA.mkdir(parents=True, exist_ok=True)

        torrc = _LOCAL_TORRC if _LOCAL_TORRC.exists() else None
        cmd = [str(tor_exe)]
        if torrc:
            cmd += ["-f", str(torrc)]

        print(f"[TOR] Starting {tor_exe} ...")
        _tor_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        # Wait up to 30s for Tor to finish bootstrapping
        deadline = time.time() + 30
        while time.time() < deadline:
            line = _tor_process.stdout.readline() if _tor_process.stdout else ""
            if "Bootstrapped 100%" in line or "Done" in line:
                print(f"[TOR] {line.strip()}")
                return True
            if line:
                print(f"[TOR] {line.strip()}")
            if _tor_process.poll() is not None:
                print("[TOR ERROR] tor.exe exited unexpectedly.")
                return False
            time.sleep(0.2)

        print("[TOR WARN] Timeout waiting for bootstrap. Proceeding anyway.")
        return True

    def stop_tor_windows(self) -> None:
        """Terminate the tor.exe process started by start_tor_windows()."""
        global _tor_process
        if _tor_process and _tor_process.poll() is None:
            _tor_process.terminate()
            _tor_process = None
            print("[TOR] tor.exe stopped.")

    def install_tor(self) -> bool:
        """Install Tor — Windows (winget) or Linux (dnf/apt)."""
        system = platform.system()

        if system == "Windows":
            return self._install_tor_windows()

        # Linux — try apt then dnf
        pkg_managers = [
            (["sudo", "apt-get", "install", "-y", "tor"], ["sudo", "systemctl", "enable", "--now", "tor"]),
            (["sudo", "dnf",     "install", "-y", "tor"], ["sudo", "systemctl", "enable", "--now", "tor"]),
        ]
        for install_cmd, start_cmd in pkg_managers:
            try:
                subprocess.run(install_cmd, check=True, capture_output=True)
                subprocess.run(start_cmd,   check=True, capture_output=True)
                time.sleep(2)
                return self.check_tor()
            except Exception:
                continue
        print("[INSTALL ERROR] Could not install Tor on Linux. Try manually: sudo apt install tor")
        return False

    def _install_tor_windows(self) -> bool:
        """Install Tor on Windows using winget, then copy tor.exe to local tor\\ folder."""
        print("[TOR] Installing via winget (Tor Browser)...")
        try:
            subprocess.run(
                [
                    "winget", "install", "TorProject.TorBrowser",
                    "--accept-package-agreements",
                    "--accept-source-agreements",
                    "--silent",
                ],
                check=True,
            )
        except Exception as e:
            print(f"[WARN] winget failed: {e}. Trying manual Expert Bundle download...")
            return self._download_tor_expert_bundle()

        # Copy tor.exe from Tor Browser installation to local tor\ folder
        tor_exe = _find_tor_exe()
        if not tor_exe:
            print("[WARN] Tor Browser installed but tor.exe not found at expected paths.")
            print("  Expected: %LOCALAPPDATA%\\Tor Browser\\Browser\\TorBrowser\\Tor\\tor.exe")
            return False

        if tor_exe != _LOCAL_TOR_EXE:
            _LOCAL_TOR_EXE.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            src_dir = tor_exe.parent
            for f in src_dir.iterdir():
                if f.suffix in (".exe", ".dll", ".so", ""):
                    shutil.copy2(f, _LOCAL_TOR_EXE.parent / f.name)
            print(f"[TOR] Copied tor.exe to {_LOCAL_TOR_EXE.parent}")

        self._write_torrc()
        time.sleep(2)
        return self.start_tor_windows() and self.check_tor()

    def _download_tor_expert_bundle(self) -> bool:
        """Download and extract the Tor Expert Bundle for Windows x64."""
        import tarfile
        import tempfile
        import urllib.request

        # Fetch latest download URL from Tor's update API
        try:
            import json, urllib.request as ur
            with ur.urlopen(
                "https://aus1.torproject.org/torbrowser/update_3/release/downloads.json",
                timeout=15,
            ) as r:
                data = json.load(r)
            eb_url = (
                data.get("downloads", {})
                    .get("win64", {})
                    .get("tor-expert-bundle")
            )
        except Exception:
            eb_url = None

        if not eb_url:
            eb_url = (
                "https://archive.torproject.org/tor-package-archive/torbrowser/"
                "14.0.9/tor-expert-bundle-windows-x86_64-14.0.3.tar.gz"
            )
            print(f"[TOR] Using fallback URL: {eb_url}")

        print(f"[TOR] Downloading Expert Bundle from {eb_url} ...")
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                urllib.request.urlretrieve(eb_url, tmp.name)
                tgz_path = tmp.name

            _LOCAL_TOR_EXE.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(tgz_path, "r:gz") as tar:
                for member in tar.getmembers():
                    # Extract only tor.exe and DLLs, strip path prefix
                    name = Path(member.name).name
                    if name.endswith((".exe", ".dll")):
                        member.name = name
                        tar.extract(member, _LOCAL_TOR_EXE.parent)

            os.unlink(tgz_path)
            print(f"[TOR] Expert Bundle extracted to {_LOCAL_TOR_EXE.parent}")
            self._write_torrc()
            return _LOCAL_TOR_EXE.exists()
        except Exception as e:
            print(f"[INSTALL ERROR] Download failed: {e}")
            print("  Manual: download from https://www.torproject.org/download/tor/")
            print(f"  Extract tor.exe and DLLs into: {_LOCAL_TOR_EXE.parent}")
            return False

    def _write_torrc(self) -> None:
        """Write default torrc if absent. Must be ASCII — no UTF-8 BOM."""
        if _LOCAL_TORRC.exists():
            return
        _LOCAL_TOR_DATA.mkdir(parents=True, exist_ok=True)
        _LOCAL_TORRC.write_text(
            f"SocksPort {TOR_SOCKS_PORT}\r\n"
            f"ControlPort {TOR_CONTROL_PORT}\r\n"
            f"DataDirectory {_LOCAL_TOR_DATA}\r\n"
            "Log notice stdout\r\n",
            encoding="ascii",   # UTF-8 BOM breaks Tor parser on Windows
        )
        print(f"[TOR] torrc written to {_LOCAL_TORRC}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proxy Manager (patent-search-engine)")
    parser.add_argument("--check",   action="store_true", help="Check if Tor SOCKS proxy is working")
    parser.add_argument("--start",   action="store_true", help="Start tor.exe in background (Windows)")
    parser.add_argument("--rotate",  action="store_true", help="Rotate Tor circuit (NEWNYM)")
    parser.add_argument("--test",    action="store_true", help="Test Google Patents connectivity via Tor")
    parser.add_argument("--install", action="store_true", help="Install Tor (Windows: winget, Linux: apt/dnf)")
    args = parser.parse_args()

    manager = ProxyManager()

    if args.check:
        ok = manager.check_tor()
        ip = manager.get_exit_ip()
        print(f"Tor working : {ok}")
        print(f"Exit IP     : {ip}")

    elif args.start:
        if platform.system() == "Windows":
            ok = manager.start_tor_windows()
            print(f"Tor started : {ok}")
        else:
            print("--start is Windows-only. On Linux, run: sudo systemctl start tor")

    elif args.rotate:
        ok = manager.rotate_tor_circuit()
        print(f"Circuit rotated: {ok}")
        time.sleep(3)
        ip = manager.get_exit_ip()
        print(f"New exit IP: {ip}")

    elif args.test:
        results = manager.test_google_patents()
        for k, v in results.items():
            print(f"  {k}: {v}")

    elif args.install:
        ok = manager.install_tor()
        print(f"Tor installed and running: {ok}")

    else:
        parser.print_help()
