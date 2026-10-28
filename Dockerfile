# Build on a verified ARM64 environment for the current AgentArts runtime.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AGENT_RUN_PORT=8080
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN useradd --uid 10001 --create-home medroute
COPY --chown=medroute:medroute *.py ./
COPY --chown=medroute:medroute data/ ./data/
USER medroute
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/ping', timeout=3)"
ENTRYPOINT ["python", "app.py"]
