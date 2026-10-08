#!/usr/bin/env python3
import base64
import json
import socket
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

MERGED_PATH = Path("output/merged.txt")
OUTPUT_PATH = Path("output/working_configs.txt")

TIMEOUT = 3.0       # Таймаут TCP-подключения (сек)
MAX_WORKERS = 100   # Параллельных проверок


def parse_host_port(link):
    """Извлекает host и port из ссылки любого протокола."""
    try:
        if link.startswith("vmess://"):
            b64 = link[len("vmess://"):].split("#")[0]
            b64 += "=" * (-len(b64) % 4)
            data = json.loads(base64.b64decode(b64).decode("utf-8", "ignore"))
            host = (data.get("add") or "").strip()
            port = data.get("port", "")
            return host, int(port) if port else None

        # vless, trojan, ss, hysteria2, hy2
        parsed = urllib.parse.urlparse(link)
        host = parsed.hostname
        port = parsed.port

        if not host or not port:
            # Fallback: ручной разбор "user@host:port?..."
            rest = link.split("://", 1)[1].split("#", 1)[0]
            if "@" in rest:
                rest = rest.split("@", 1)[1]
            host_port = rest.split("/", 1)[0].split("?", 1)[0]
            if ":" in host_port:
                h, p = host_port.rsplit(":", 1)
                host = h
                port = p

        if host and port:
            return host.strip(), int(port)
    except Exception:
        pass
    return None, None


def tcp_check(host, port):
    """Проверяет, открыт ли TCP-порт."""
    try:
        with socket.create_connection((host, port), timeout=TIMEOUT):
            return True
    except Exception:
        return False


def main():
    if not MERGED_PATH.exists():
        print("[!] output/merged.txt не найден")
        return 1

    links = []
    for line in MERGED_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "://" in line and not line.startswith("#"):
            links.append(line)

    print(f"[=] Всего ссылок: {len(links)}")
    if not links:
        print("[!] Нет ссылок")
        return 0

    # Готовим список (link, host, port)
    tasks = []
    for link in links:
        host, port = parse_host_port(link)
        if host and port:
            tasks.append((link, host, port))
        else:
            print(f"[!] Не удалось распарсить: {link[:80]}")

    print(f"[=] К проверке: {len(tasks)}")

    # Параллельная TCP-проверка
    working = []
    dead = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(tcp_check, h, p): link for link, h, p in tasks}
        for i, fut in enumerate(as_completed(futures), 1):
            link = futures[fut]
            try:
                if fut.result():
                    working.append(link)
            except Exception:
                dead += 1
            if i % 50 == 0:
                print(f"  [{i}/{len(tasks)}] рабочих: {len(working)}, мёртвых: {dead}")

    print(f"[✓] TCP-проверка завершена: {len(working)} рабочих из {len(tasks)}")
    print(f"[=] Отсеяно мёртвых: {len(tasks) - len(working)}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(working), encoding="utf-8")
    print(f"[✓] Сохранено в {OUTPUT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())