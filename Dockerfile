# Printer Dashboard - Fuji Xerox (ApeosPort) supplies monitor
#
# Python standard library only: there are no packages to install.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Jakarta

WORKDIR /app

# Application code and web assets.
COPY app.py collector.py config.json ./
COPY web ./web

# Runtime data (state/history/stock) is normally a bind-mounted volume;
# create the directory so the image also works without a mount.
RUN mkdir -p /app/data

EXPOSE 8080

# app.py starts the HTTP server and the background collector thread.
CMD ["python", "app.py"]
