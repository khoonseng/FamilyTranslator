# Built by Cloud Build from the folder deploy.sh stages (lib/, probe/, config, prompts only).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD exec uvicorn probe.app:app --host 0.0.0.0 --port ${PORT:-8080}
