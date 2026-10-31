FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    STORAGE_BACKEND=telegram DATABASE_URL=sqlite:////tmp/kdrama.db TIMEZONE=Asia/Kolkata PORT=8000
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd --create-home --uid 10001 bot && chown -R bot:bot /app
USER bot
EXPOSE 8000
CMD ["python", "main.py"]
