FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    STORAGE_BACKEND=telegram \
    DATABASE_URL=sqlite:////tmp/kdrama.db \
    TIMEZONE=Asia/Kolkata \
    PORT=8000

WORKDIR /app

# Install deps first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (main.py must be at /app/main.py)
COPY main.py config.py db.py services.py keyboards.py jobs.py utils.py storage.py health.py ./
COPY handlers ./handlers
COPY run.sh ./
RUN chmod +x run.sh

RUN useradd --create-home --uid 10001 bot && chown -R bot:bot /app
USER bot

EXPOSE 8000

# Exec form so Koyeb / Docker always get a start command
ENTRYPOINT ["python", "-u"]
CMD ["main.py"]
