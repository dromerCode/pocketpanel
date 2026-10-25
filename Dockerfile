FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY web ./web
ENV HOME=/tmp USER=pocketpanel PYTHONUNBUFFERED=1 PANEL_PORT=9300 PANEL_BIND=127.0.0.1 PANEL_TRUSTED_PROXIES=127.0.0.1
CMD ["sh", "-c", "exec uvicorn app.main:app --host \"$PANEL_BIND\" --port \"$PANEL_PORT\" --proxy-headers --forwarded-allow-ips \"$PANEL_TRUSTED_PROXIES\""]
