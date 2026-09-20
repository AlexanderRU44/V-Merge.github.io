#!/usr/bin/env python3
"""
V-Merge auto-builder.
Скачивает источники из sources.txt, объединяет, убирает дубли,
определяет страну по IP, переименовывает и пишет:
  - output/merged.txt        (plain)
  - output/merged.base64.txt (base64-подписка)
"""
import base64
import ipaddress
import json
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "scripts" / "sources.txt"
GEO_CACHE = ROOT / "scripts" / "geo_cache.json"
OUT_PLAIN = ROOT / "output" / "merged.txt"
OUT_B64 = ROOT / "output" / "merged.base64.txt"

FLAGS = {
    "RU": "🇷🇺 RU", "US": "🇺🇸 US", "DE": "🇩🇪 DE", "NL": "🇳🇱 NL",
    "FR": "🇫🇷 FR", "GB": "🇬🇧 GB", "FI": "🇫🇮 FI", "SE": "🇸🇪 SE",
    "TR": "🇹🇷 TR", "JP": "🇯🇵 JP", "KR": "🇰🇷 KR", "SG": "🇸🇬 SG",
    "CA": "🇨🇦 CA", "PL": "🇵🇱 PL", "UA": "🇺🇦 UA", "KZ": "🇰🇿 KZ",
    "CN": "🇨🇳 CN", "HK": "🇭🇰 HK", "IN": "🇮🇳 IN", "BR": "🇧🇷 BR",
    "IR": "🇮🇷 IR", "AE": "🇦🇪 AE", "IT": "🇮🇹 IT", "ES": "🇪🇸 ES",
    "CH": "🇨🇭 CH", "AT": "🇦🇹 AT", "CZ": "🇨🇿 CZ", "RO": "🇷🇴 RO",
    "MD": "🇲🇩 MD", "LV": "🇱🇻 LV", "LT": "🇱🇹 LT", "EE": "🇪🇪 EE",
    "AM": "🇦🇲 AM", "GE": "🇬🇪 GE", "AZ": "🇦🇿 AZ", "IL": "🇮🇱 IL",
    "AU": "🇦🇺 AU", "NZ": "🇳🇿 NZ", "MX": "🇲🇽 MX", "AR": "🇦🇷 AR",
}

UA = "Mozilla/5.0 (compatible; V-Merge-Bot/1.0)"


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def decode_subscription(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    if "://" in text:
        return text
    try:
        cleaned = re.sub(r"\s+", "", text)
        cleaned += "=" * (-len(cleaned) % 4)
        decoded = base64.b64decode(cleaned).decode("utf-8", errors="ignore")
        if "://" in decoded:
            return decoded
    except Exception:
        pass
    return text


def load_cache() -> dict:
    if GEO_CACHE.exists():
        try:
            return json.loads(GEO_CACHE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    GEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEO_CACHE.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def ip_to_country(host: str, cache: dict) -> str:
    if not host:
        return "XX"
    if host in cache:
        return cache[host]

    country = "XX"
    try:
        ipaddress.ip_address(host)
        ip = host
    except ValueError:
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            cache[host] = "XX"
            return "XX"

    try:
        with urllib.request.urlopen(
            f"http://ip-api.com/json/{ip}?fields=countryCode", timeout=10
        ) as r:
            data = json.loads(r.read().decode())
            country = (data.get("countryCode") or "XX").upper()
        time.sleep(0.2)  # мягко к API (лимит 45/мин)
    except Exception:
        country = "XX"

    cache[host] = country
    return country


def extract_host(link: str) -> str | None:
    try:
        if link.startswith("vmess://"):
            b64 = link[len("vmess://"):]
            b64 += "=" * (-len(b64) % 4)
            data = json.loads(
                base64.b64decode(b64).decode("utf-8", errors="ignore")
            )
            return data.get("add") or data.get("host")
        parsed = urllib.parse.urlparse(link)
        if parsed.hostname:
            return parsed.hostname
        if "@" in link:
            after = link.split("@", 1)[1]
            return after.split(":", 1)[0].split("/", 1)[0].split("?", 1)[0]
    except Exception:
        return None
    return None


def rename_link(link: str, country: str, idx: int) -> str:
    label = FLAGS.get(country, f"🏴 {country}")
    tag = f"{label} #{idx}"

    if link.startswith("vmess://"):
        try:
            b64 = link[len("vmess://"):]
            b64 += "=" * (-len(b64) % 4)
            data = json.loads(
                base64.b64decode(b64).decode("utf-8", errors="ignore")
            )
            data["ps"] = tag
            new_b64 = base64.b64encode(
                json.dumps(data, ensure_ascii=False).encode("utf-8")
            ).decode()
            return "vmess://" + new_b64
        except Exception:
            return link

    base = link.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(tag)}"


def main() -> int:
    if not SOURCES.exists():
        print("[!] Нет scripts/sources.txt", file=sys.stderr)
        return 1

    urls = [
        l.strip() for l in SOURCES.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]
    if not urls:
        print("[!] sources.txt пустой — нечего собирать", file=sys.stderr)
        OUT_PLAIN.parent.mkdir(parents=True, exist_ok=True)
        OUT_PLAIN.write_text("", encoding="utf-8")
        OUT_B64.write_text("", encoding="utf-8")
        return 0

    all_links: list[str] = []
    for url in urls:
        try:
            print(f"[+] Загрузка: {url}")
            raw = fetch(url)
            decoded = decode_subscription(raw)
            for line in decoded.splitlines():
                line = line.strip()
                if "://" in line and not line.startswith("#"):
                    all_links.append(line)
        except Exception as e:
            print(f"[!] Ошибка {url}: {e}", file=sys.stderr)

    all_links = list(dict.fromkeys(all_links))
    print(f"[=] Уникальных ссылок: {len(all_links)}")

    cache = load_cache()
    result: list[str] = []
    for i, link in enumerate(all_links, 1):
        host = extract_host(link)
        country = ip_to_country(host, cache) if host else "XX"
        result.append(rename_link(link, country, i))
        print(f"  {i}. {country} — {host}")

    save_cache(cache)

    plain = "\n".join(result)
    if result:
        plain += "\n"
    OUT_PLAIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAIN.write_text(plain, encoding="utf-8")
    OUT_B64.write_text(
        base64.b64encode(plain.encode("utf-8")).decode(), encoding="utf-8"
    )
    print(f"[✓] {OUT_PLAIN} ({len(result)} шт.)")
    print(f"[✓] {OUT_B64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
