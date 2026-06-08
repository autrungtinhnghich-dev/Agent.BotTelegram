FROM python:3.12-slim

# Cài đặt nodejs để làm JS runtime giải mã signature/challenge của YouTube
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Cài dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source
COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "main.py"]
