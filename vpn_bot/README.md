# VPN Config Bot

Бот для выдачи рабочих VPN-конфигов из репозитория V-Merge.

## Запуск на Render
1. Создайте Web Service (или Background Worker).
2. Укажите репозиторий и ветку `main`.
3. **Root Directory**: `vpn_bot`
4. **Environment**: `Docker`
5. **Environment Variables**:
   - `TELEGRAM_TOKEN` — токен от BotFather
   - `GITHUB_TOKEN` — Personal Access Token (для сохранения состояния)
