#!/usr/bin/env python3
"""
V-Merge auto-builder.

Делает всё:
  1. Скачивает источники из sources.txt
  2. Декодирует base64-подписки
  3. Удаляет дубликаты по (type, host, port)
  4. Для новых хостов досыпает страну в scripts/geo_cache.json (ip-api.com)
  5. Пишет output/merged.txt        — оригинальные ссылки (для клиентов и программы добавления)
  6. Пишет output/merged.base64.txt — то же в base64 (готовая подписка)

index.html на сайте сам парсит ссылки и показывает таблицу со странами из geo_cache.json.
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

# ---- Настройки авто-обновления кэша ----
GEO_ENABLED = True      # False — выключить геолокацию
MAX_NEW = 200           # сколько новых хостов обрабатывать за прогон
DELAY_BETWEEN = 1.5     # пауза между запросами (ip-api.com: 45/мин)
# -----------------------------------------


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def decode_subscription(text: str) -> str:
    """Если текст — base64-подписка, декодирует. Иначе возвращает как есть."""
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


# ---------- Геолокация ----------

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


def resolve_ip(host: str) -> str | None:
    """Если это IP — вернёт его. Если домен — резолвит."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        try:
            return socket.gethostbyname(host)
        except Exception:
            return None


def lookup_country_ip(ip: str) -> str:
    """Спрашивает ip-api.com. Возвращает код страны или 'XX'."""
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


def update_geo_cache(hosts: list[str], geo: dict) -> dict:
    """Досыпает страны для новых хостов (с лимитом на прогон)."""
    if not GEO_ENABLED:
        return geo

    missing: list[str] = []
    seen: set[str] = set()
    for h in hosts:
        hl = h.strip().lower()
        if not hl or hl == "-" or hl in geo or hl in seen:
            continue
        seen.add(hl)
        missing.append(hl)

    print(f"[=] Новых хостов для геолокации: {len(missing)}")
    if not missing:
        return geo

    to_process = missing[:MAX_NEW]
    print(f"[=] Обрабатываю {len(to_process)} (лимит {MAX_NEW})")

    added = 0
    for i, host in enumerate(to_process, 1):
        ip = resolve_ip(host)
        if not ip:
            geo[host] = "XX"
            print(f"  [{i}/{len(to_process)}] {host} — не резолвится (XX)")
            continue

        cc = lookup_country_ip(ip)
        geo[host] = cc
        if cc != "XX":
            added += 1
        print(f"  [{i}/{len(to_process)}] {host} → {ip} → {cc}")
        time.sleep(DELAY_BETWEEN)

    remaining = len(missing) - len(to_process)
    if remaining > 0:
        print(f"[i] Осталось на следующий прогон: {remaining}")

    print(f"[=] Добавлено новых стран: {added}")
    return geo


# ---------- Основной сценарий ----------

def main() -> int:
    if not SOURCES.exists():
        print("[!] Нет scripts/sources.txt", file=sys.stderr)
        return 1

    urls = [
        l.strip() for l in SOURCES.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]

    # 1. Скачиваем и объединяем
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

    print(f"[=] Всего строк после чтения: {len(all_links)}")

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
    print(f"[=] После дедупликации (type+host+port): {len(all_links)}")

    # 3. Собираем хосты для геолокации
    hosts: list[str] = []
    for link in all_links:
        _, h, _ = parse_link(link)
        if h:
            hosts.append(h)

    # 4. Обновляем geo_cache.json
    geo = load_geo()
    print(f"[=] Записей в кэше до обновления: {len(geo)}")
    geo = update_geo_cache(hosts, geo)
    save_geo(geo)
    print(f"[=] Записей в кэше после обновления: {len(geo)}")

    # 5. Пишем оригинальные ссылки в merged.txt
    text = "\n".join(all_links)
    if all_links:
        text += "\n"

    OUT_PLAIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAIN.write_text(text, encoding="utf-8")
    OUT_B64.write_text(
        base64.b64encode(text.encode("utf-8")).decode(), encoding="utf-8"
    )
    print(f"[✓] {OUT_PLAIN} ({len(all_links)} шт.)")
    print(f"[✓] {OUT_B64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
