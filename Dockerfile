FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Jakarta
WORKDIR /app
COPY app.py collector.py worker.py storage.py runtime.py ./
RUN mkdir -p /app/data
EXPOSE 8080
CMD ["python", "app.py"]
