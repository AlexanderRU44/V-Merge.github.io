#!/usr/bin/env python3
"""
V-Merge auto-builder.
Объединяет конфиги из sources.txt, удаляет дубликаты
по (type, address, port), пишет TSV: num \t type \t address \t port
"""
import base64
import json
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "scripts" / "sources.txt"
OUT_PLAIN = ROOT / "output" / "merged.txt"
OUT_B64 = ROOT / "output" / "merged.base64.txt"

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


def main() -> int:
    if not SOURCES.exists():
        print("[!] Нет scripts/sources.txt", file=sys.stderr)
        return 1

    urls = [
        l.strip() for l in SOURCES.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.lstrip().startswith("#")
    ]

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

    # ---- Дедупликация по (type, host, port) ----
    seen = set()
    unique_links = []
    for link in all_links:
        t, h, p = parse_link(link)
        if t and h:
            key = (t, h, p)
        else:
            key = ("__raw__", link, "")
        if key in seen:
            continue
        seen.add(key)
        unique_links.append(link)

    all_links = unique_links
    print(f"[=] После дедупликации (type+host+port): {len(all_links)}")

    # ---- Пишем TSV ----
    rows = []
    for i, link in enumerate(all_links, 1):
        t, h, p = parse_link(link)
        rows.append(f"{i}\t{t or 'unknown'}\t{h or '-'}\t{p or '-'}")

    text = "\n".join(rows)
    if rows:
        text += "\n"

    OUT_PLAIN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAIN.write_text(text, encoding="utf-8")
    OUT_B64.write_text(
        base64.b64encode(text.encode("utf-8")).decode(), encoding="utf-8"
    )
    print(f"[✓] {OUT_PLAIN} ({len(rows)} шт.)")
    print(f"[✓] {OUT_B64}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
