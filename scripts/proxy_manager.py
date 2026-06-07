#!/usr/bin/env python3
"""
ProxyManager — Reference implementation for patent-search-engine skill.

Manages Tor proxy, rotation, and health checks. Placeholder for future
residential proxy integration (Bright Data, ScrapingBee, etc.).

Usage:
    python proxy_manager.py --check
    python proxy_manager.py --rotate
    python proxy_manager.py --test
"""

import argparse
import socket
import subprocess
import time
from typing import Optional

import requests

TOR_PROXY = "socks5://127.0.0.1:9050"
TOR_CONTROL_PORT = 9051
TOR_CONTROL_PASSWORD = ""  # Set if Tor control port is authenticated


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

    def install_tor(self) -> bool:
        """Install and start Tor (Rocky Linux / RHEL / Fedora)."""
        try:
            subprocess.run(
                ["sudo", "dnf", "install", "-y", "tor"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["sudo", "systemctl", "enable", "--now", "tor"],
                check=True,
                capture_output=True,
            )
            # Verify
            time.sleep(2)
            return self.check_tor()
        except Exception as e:
            print(f"[INSTALL ERROR] {e}")
            return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Proxy Manager")
    parser.add_argument("--check", action="store_true", help="Check Tor status")
    parser.add_argument("--rotate", action="store_true", help="Rotate Tor circuit")
    parser.add_argument("--test", action="store_true", help="Test Google Patents connectivity")
    parser.add_argument("--install", action="store_true", help="Install and start Tor")
    args = parser.parse_args()

    manager = ProxyManager()

    if args.check:
        ok = manager.check_tor()
        ip = manager.get_exit_ip()
        print(f"Tor working: {ok}")
        print(f"Exit IP: {ip}")

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
