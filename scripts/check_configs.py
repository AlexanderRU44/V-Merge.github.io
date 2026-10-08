#!/usr/bin/env python3
import sys
from pathlib import Path

from python_v2ray.downloader import BinaryDownloader
from python_v2ray.tester import ConnectionTester
from python_v2ray.config_parser import parse_uri


def main():
    merged_path = Path("output/merged.txt")
    if not merged_path.exists():
        print("[!] output/merged.txt не найден")
        return 1

    # 1. Читаем ссылки, пропускаем комментарии
    links = []
    for line in merged_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "://" in line and not line.startswith("#"):
            links.append(line)

    print(f"[=] Прочитано ссылок: {len(links)}")
    if not links:
        print("[!] Нет ссылок для проверки")
        return 0

    # 2. Скачиваем бинарники (Xray-core и т.д.)
    project_root = Path("./")
    print("[=] Проверка бинарников...")
    try:
        downloader = BinaryDownloader(project_root)
        downloader.ensure_all()
    except Exception as e:
        print(f"[!] Ошибка скачивания бинарников: {e}")
        return 1

    # 3. Парсим ссылки
    print("[=] Парсинг ссылок...")
    parsed_configs = []
    for link in links:
        try:
            cfg = parse_uri(link)
            if cfg:
                parsed_configs.append(cfg)
        except Exception:
            pass

    print(f"[=] Успешно распарсено: {len(parsed_configs)}")
    if not parsed_configs:
        print("[!] Не удалось распарсить ни одной ссылки")
        return 0

    # 4. Тестируем
    print(f"[=] Тестирование {len(parsed_configs)} конфигов (это может занять время)...")
    tester = ConnectionTester(
        vendor_path=str(project_root / "vendor"),
        core_engine_path=str(project_root / "core_engine"),
    )

    try:
        results = tester.test_uris(parsed_configs)
    except Exception as e:
        print(f"[!] Ошибка во время тестирования: {e}")
        return 1

    # 5. Отбираем рабочие (пинг > 0)
    working_links = []
    for i, res in enumerate(results):
        ping = res.get("ping_ms", 0) if isinstance(res, dict) else getattr(res, "ping_ms", 0)
        if ping and ping > 0:
            working_links.append(links[i])

    print(f"[✓] Рабочих конфигов: {len(working_links)} из {len(links)}")

    # 6. Сохраняем
    output_path = Path("output/working_configs.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(working_links), encoding="utf-8")
    print(f"[✓] Сохранено в {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
