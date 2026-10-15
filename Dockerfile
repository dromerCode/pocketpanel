FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
ENV HOME=/tmp USER=pocketpanel PYTHONUNBUFFERED=1 PANEL_PORT=9300
CMD ["sh", "-c", "exec uvicorn app.main:app --host 127.0.0.1 --port ${PANEL_PORT} --proxy-headers --forwarded-allow-ips 127.0.0.1"]
