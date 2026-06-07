# Anti-Scraping Mechanisms & Countermeasures

## Google Patents Blocking Stack

Google Patents uses a multi-layer defense system against automated access.

### Layer 1: IP Reputation

| IP Type | Blocked? | Evidence |
|---------|----------|----------|
| Oracle Cloud (Oracle) | ❌ Yes | 503 on all endpoints |
| AWS EC2 | ❌ Yes | Community reports |
| Azure VM | ❌ Yes | Community reports |
| Google Cloud | ✅ Sometimes works | Same ASN as Google → less suspicious |
| Residential ISP | ✅ Works | Standard home/work IP |
| Tor exit node | ⚠️ Sometimes | Rotates; some exits blocked |
| VPN (commercial) | ⚠️ Sometimes | Known VPN IP ranges may be flagged |

**Detection**: `curl -4 -s https://api.ipify.org` → if the IP belongs to a known
data center ASN (AS31898 for Oracle, AS16509 for AWS, AS8075 for Azure), expect
a block.

### Layer 2: Request Fingerprinting

| Signal | Automated vs Browser |
|--------|---------------------|
| User-Agent | `python-requests/2.31.0` → flagged; real Chrome UA → better |
| Accept header | Missing `Accept: application/json` → flagged |
| Accept-Language | Missing → slightly suspicious |
| Referer | Missing → suspicious |
| Cookie | Fresh session vs no cookies → no cookies flagged |
| TLS fingerprint | `requests` uses OpenSSL → different from Chrome/BoringSSL |
| HTTP/2 | `requests` uses HTTP/1.1 → Chrome uses HTTP/2 |
| HTTP/3 | Chrome may use HTTP/3 → `requests` never does |

**Mitigation**: Use a real browser's exact headers. Still may fail if IP is blacklisted.

```python
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://patents.google.com/",
    "X-Requested-With": "XMLHttpRequest",
}
```

### Layer 3: JavaScript Challenges

Google Patents occasionally serves JavaScript-encrypted pages that require execution
to decode the actual content. Standard `requests` cannot execute JS.

**Mitigation**: Not practical to bypass from a headless VM without a real browser.
Use EPO OPS instead.

### Layer 4: reCAPTCHA

Triggered when:
- Too many requests from same IP
- Suspicious request pattern (no Referer, wrong UA)
- Rapid sequential page requests

**Mitigation**: No reliable automated solution. Use official API (EPO OPS) instead.

---

## Tor Proxy Strategy

### Setup

```bash
# Rocky Linux / RHEL / Fedora
sudo dnf install -y tor
sudo systemctl enable --now tor

# Verify
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org
```

### Python Integration

```python
import requests

session = requests.Session()
session.proxies = {
    "http": "socks5://127.0.0.1:9050",
    "https": "socks5://127.0.0.1:9050",
}

# Use requests[socks] or install pysocks
# uv pip install requests[socks]
```

### Circuit Rotation

```bash
# Send NEWNYM signal to Tor to rotate circuit
sudo killall -HUP tor
# Or use torctl
```

```python
import socket

def renew_tor_circuit():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect(("127.0.0.1", 9051))
        s.sendall(b'AUTHENTICATE "password"\r\n')
        s.sendall(b"SIGNAL NEWNYM\r\n")
```

### Limitations

- Tor exit nodes are public → some are blacklisted by Google
- Bandwidth: ~50–100 KB/s per circuit
- Latency: ~500ms–2s per request
- Not suitable for bulk PDF downloads

**Recommendation**: Use Tor for **search API calls** (lightweight), but **avoid**
for PDF downloads (slow). For PDFs, try direct download first — Google Patents CDN
(`patentimages.storage.googleapis.com`) often works even when search is blocked.

---

## Alternative: Residential Proxies

For production-scale patent collection, residential proxies are more reliable than Tor.

| Provider | Type | Cost | Notes |
|----------|------|------|-------|
| Bright Data | Residential | Pay-per-GB | Rotating IPs, good success rate |
| ScrapingBee | API proxy | Pay-per-request | Handles retries, JS rendering |
| Oxylabs | Residential | Pay-per-GB | Large IP pool |
| Smartproxy | Residential | Pay-per-GB | Good for US/EU IPs |

**Not implemented in this skill** — add `ProxyManager` subclass if needed.

---

## EPO OPS: The Official Alternative

Instead of fighting anti-scraping, use the official API.

**Registration**: https://developers.epo.org/

**Advantages**:
- ✅ Official API (no scraping fragility)
- ✅ Global patent coverage (DOCDB)
- ✅ Not blocked from cloud VMs
- ✅ Consistent JSON/XML responses
- ✅ No rate limiting for moderate use

**Limitations**:
- ❌ 1,000 requests/week (free tier)
- ❌ OAuth 2.0 required (Client ID + Secret)
- ❌ Patent images require separate endpoint
- ❌ No citation counts (need USPTO PAIR for that)

**See `references/epo_ops.md` for full implementation guide.**

---

## Detection Checklist

Before concluding "Google Patents is blocked", verify:

```bash
# 1. Is it the IP?
curl -4 -s https://api.ipify.org
curl -4 -s https://api.ip.sb

# 2. Is it Tor?
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org

# 3. Is the endpoint itself down?
curl -I https://patents.google.com/

# 4. Does CDN still work?
curl -I https://patentimages.storage.googleapis.com/

# 5. Is it DNS?
nslookup patents.google.com

# 6. Is it TLS?
curl -v https://patents.google.com/xhr/query?url=q%3Dtest
```

| Check | Expected | If wrong |
|-------|----------|----------|
| IP is data center | Blocked likely | Use Tor or EPO OPS |
| Tor check OK | Tor working | Restart Tor |
| patents.google.com down | Rare | Wait or use EPO OPS |
| CDN works | Images available | Only search is blocked |
| DNS fails | Network issue | Check VM networking |
| TLS handshake fails | Cert/clock issue | Check system time |
