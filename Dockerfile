FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SIGNAL_DATA_DIR=/data
WORKDIR /app
RUN groupadd --gid 10001 signal && useradd --uid 10001 --gid signal --no-create-home signal \
    && mkdir /data && chown signal:signal /data
COPY --chown=signal:signal *.py rootdata-team.json ./
COPY --chown=signal:signal dist/ ./dist/
USER signal
EXPOSE 4317
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4317/healthz',timeout=3).read()"
CMD ["python", "server.py"]
