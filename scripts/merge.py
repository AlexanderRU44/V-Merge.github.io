#!/usr/bin/env python3
"""
V-Merge auto-builder.

  1. Скачивает источники из sources.txt
  2. Декодирует base64-подписки
  3. Удаляет дубликаты по (type, host, port)
  4. Досыпает страны в scripts/geo_cache.json (ip-api.com)
     — включая перезапрос записей со значением "XX"
  5. Жёстко перезаписывает имя каждой ссылки: "🇩🇪 DE #N"
  6. Пишет output/merged.txt и output/merged.base64.txt
"""
import base64
import ipaddress
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "scripts" / "sources.txt"
GEO_CACHE = ROOT / "scripts" / "geo_cache.json"
OUT_PLAIN = ROOT / "output" / "merged.txt"
OUT_B64 = ROOT / "output" / "merged.base64.txt"

UA = "Mozilla/5.0 (compatible; V-Merge-Bot/1.0)"

# ---- Настройки ----
GEO_ENABLED = True       # False — выключить геолокацию
MAX_NEW = 200            # сколько хостов обрабатывать за прогон (вкл. XX)
DELAY_BETWEEN = 1.5      # пауза между запросами (ip-api.com: 45/мин)
RENAME_ENABLED = True    # переименовывать ссылки в "🇩🇪 DE #N"
# -------------------

FLAGS = {
    "RU": "🇷🇺", "US": "🇺🇸", "DE": "🇩🇪", "NL": "🇳🇱", "FR": "🇫🇷",
    "GB": "🇬🇧", "FI": "🇫🇮", "SE": "🇸🇪", "TR": "🇹🇷", "JP": "🇯🇵",
    "KR": "🇰🇷", "SG": "🇸🇬", "CA": "🇨🇦", "PL": "🇵🇱", "UA": "🇺🇦",
    "KZ": "🇰🇿", "CN": "🇨🇳", "HK": "🇭🇰", "IN": "🇮🇳", "BR": "🇧🇷",
    "IR": "🇮🇷", "AE": "🇦🇪", "IT": "🇮🇹", "ES": "🇪🇸", "CH": "🇨🇭",
    "AT": "🇦🇹", "CZ": "🇨🇿", "RO": "🇷🇴", "MD": "🇲🇩", "LV": "🇱🇻",
    "LT": "🇱🇹", "EE": "🇪🇪", "AM": "🇦🇲", "GE": "🇬🇪", "AZ": "🇦🇿",
    "IL": "🇮🇱", "AU": "🇦🇺", "NZ": "🇳🇿", "MX": "🇲🇽", "AR": "🇦🇷",
    "BG": "🇧🇬", "RS": "🇷🇸", "HR": "🇭🇷", "SK": "🇸🇰", "SI": "🇸🇮",
    "TH": "🇹🇭", "VN": "🇻🇳", "MY": "🇲🇾", "ID": "🇮🇩", "PH": "🇵🇭",
    "NO": "🇳🇴", "DK": "🇩🇰", "BE": "🇧🇪", "IE": "🇮🇪", "PT": "🇵🇹",
    "GR": "🇬🇷", "HU": "🇭🇺", "AL": "🇦🇱", "IM": "🇮🇲",
}


def flag(cc: str) -> str:
    return FLAGS.get(cc, "🏴")


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


def parse_link(link: str):
    """Возвращает (type, host, port) или (None, None, None)."""
    try:
        if link.startswith("vmess://"):
            b64 = link[len("vmess://"):]
            b64 += "=" * (-len(b64) % 4)
            data = json.loads(
                base64.b64decode(b64).decode("utf-8", errors="ignore")
            )
            host = (data.get("add") or data.get("host") or "").strip().lower()
            port = str(data.get("port", "")).strip()
            return "vmess", host, port

        type_ = link.split("://", 1)[0].lower()
        parsed = urllib.parse.urlparse(link)
        host = (parsed.hostname or "").strip().lower()
        port = str(parsed.port or "").strip()

        if not host and "@" in link:
            after = link.split("@", 1)[1]
            host_port = after.split("/", 1)[0].split("?", 1)[0]
            if ":" in host_port:
                h, p = host_port.rsplit(":", 1)
                host = h.strip().lower()
                port = p.strip()
            else:
                host = host_port.strip().lower()

        return type_, host, port
    except Exception:
        return None, None, None


def rename_link(link: str, tag: str) -> str:
    """Полностью заменяет имя. Старое — стирается."""
    if not RENAME_ENABLED:
        return link

    # vmess:// — меняем "ps" в base64-JSON
    if link.startswith("vmess://"):
        try:
            b64 = link[len("vmess://"):]
            b64 += "=" * (-len(b64) % 4)
            raw = base64.b64decode(b64).decode("utf-8", errors="ignore")
            data = json.loads(raw)
            data["ps"] = tag
            new_b64 = base64.b64encode(
                json.dumps(data, ensure_ascii=False).encode("utf-8")
            ).decode()
            return "vmess://" + new_b64
        except Exception:
            return link

    # vless:// trojan:// hysteria2:// ss:// ... — режем всё после "#"
    base = link.split("#", 1)[0]
    return f"{base}#{urllib.parse.quote(tag)}"


def load_geo() -> dict:
    if not GEO_CACHE.exists():
        return {}
    try:
        data = json.loads(GEO_CACHE.read_text(encoding="utf-8"))
        return {
            str(k).strip().lower(): str(v).strip().upper()
            for k, v in data.items()
        }
    except Exception as e:
        print(f"[!] Ошибка чтения geo_cache.json: {e}", file=sys.stderr)
        return {}


def save_geo(data: dict) -> None:
    GEO_CACHE.parent.mkdir(parents=True, exist_ok=True)
    GEO_CACHE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def resolve_ip(host: str):
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        try:
            return socket.gethostbyname(host)
        except Exception:
            return None


def lookup_country_ip(ip: str) -> str:
    url = f"http://ip-api.com/json/{ip}?fields=status,countryCode"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            if data.get("status") == "success":
                return (data.get("countryCode") or "XX").upper()
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("[!] 429 Too Many Requests — пауза 60 сек")
            time.sleep(60)
    except Exception as e:
        print(f"  [!] ip-api: {e}")
    return "XX"


def update_geo_cache(hosts: list, geo: dict) -> dict:
    """
    Досыпает и перепроверяет страны.
    - Новые хосты (нет в geo)         → запрос к ip-api
    - Записи со значением "XX"        → перезапрос
    - Записи с реальной страной       → пропуск
    """
    if not GEO_ENABLED:
        return geo

    missing, seen = [], set()
    for h in hosts:
        hl = h.strip().lower()
        if not hl or hl == "-" or hl in seen:
            continue
        # пропускаем только те, где уже есть реальная страна
        if hl in geo and geo[hl] != "XX":
            continue
        seen.add(hl)
        missing.append(hl)

    print(f"[=] Хостов к обработке (новые + XX): {len(missing)}")
    if not missing:
        return geo

    to_process = missing[:MAX_NEW]
    print(f"[=] Обрабатываю {len(to_process)} (лимит {MAX_NEW})")

    added = 0
    improved = 0
    for i, host in enumerate(to_process, 1):
        was = geo.get(host, "")
        ip = resolve_ip(host)
        if not ip:
            geo[host] = "XX"
            print(f"  [{i}/{len(to_process)}] {host} — не резолвится (XX)")
            continue

        cc = lookup_country_ip(ip)
        geo[host] = cc
        if cc != "XX":
            added += 1
            if was == "XX":
                improved += 1
        print(f"  [{i}/{len(to_process)}] {host} → {ip} → {cc}")
        time.sleep(DELAY_BETWEEN)

    remaining = len(missing) - len(to_process)
    if remaining > 0:
        print(f"[i] Осталось на следующий прогон: {remaining}")

    print(f"[=] Определено стран: {added} (из них исправлено XX→страна: {improved})")
    return geo


def main() -> int:
    if not SOURCES.exists():
        print("[!] Нет scripts/sources.txt", file=sys.stderr)
        return 1

    urls = [
        l.strip() for l in SOURCES.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]

    # 1. Скачиваем
    all_links = []
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

    print(f"[=] Всего строк: {len(all_links)}")

    # 2. Дедупликация по (type, host, port)
    seen = set()
    unique_links = []
    for link in all_links:
        t, h, p = parse_link(link)
        key = (t, h, p) if (t and h) else ("__raw__", link, "")
        if key in seen:
            continue
        seen.add(key)
        unique_links.append(link)
    all_links = unique_links
    print(f"[=] После дедупликации: {len(all_links)}")

    # 3. Хосты для геолокации
    hosts = [h for _, h, _ in (parse_link(l) for l in all_links) if h]

    # 4. Обновляем geo_cache.json
    geo = load_geo()
    print(f"[=] Записей в кэше до: {len(geo)}")
    geo = update_geo_cache(hosts, geo)
    save_geo(geo)
    print(f"[=] Записей в кэше после: {len(geo)}")

    # 5. Переименование — жёсткая замена на "🇩🇪 DE #N"
    renamed = []
    counter = {}
    for link in all_links:
        _, h, _ = parse_link(link)
        cc = geo.get(h.lower(), "XX") if h else "XX"
        counter[cc] = counter.get(cc, 0) + 1
        tag = f"{flag(cc)} {cc} #{counter[cc]}"
        renamed.append(rename_link(link, tag))

    # 6. Пишем файлы
    text = "\n".join(renamed)
    if renamed:
        text += "\n"

    OUT_PLAIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAIN.write_text(text, encoding="utf-8")
    OUT_B64.write_text(
        base64.b64encode(text.encode("utf-8")).decode(), encoding="utf-8"
    )
    print(f"[✓] {OUT_PLAIN} ({len(renamed)} шт.)")
    print(f"[✓] {OUT_B64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
