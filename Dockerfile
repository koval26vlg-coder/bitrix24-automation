FROM python:3.10-slim

# Установка системных зависимостей, включая ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копирование требований и установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода проекта
COPY . .

# Создание папки для отчетов
RUN mkdir -p reports/audio reports/audio_ui

# Команда по умолчанию (можно переопределить в docker-compose)
CMD ["python", "bitnewton_sync_to_api.py", "--help"]
