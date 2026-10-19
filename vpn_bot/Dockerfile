FROM python:3.11-slim

# Устанавливаем зависимости для скачивания и распаковки xray
RUN apt-get update && apt-get install -y \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Скачиваем и устанавливаем xray-core
# (Ссылка на последнюю версию может меняться, лучше проверять на github.com/XTLS/Xray-core/releases)
RUN curl -L -o /tmp/xray.zip https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip \
    && unzip /tmp/xray.zip -d /usr/local/bin/ \
    && rm /tmp/xray.zip \
    && chmod +x /usr/local/bin/xray

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Запуск бота
CMD ["python", "bot.py"]
