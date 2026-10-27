FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=2 ASR_THREADS=2 MODEL_DIR=/opt/atow-models \
    DATA_DIR=/data PUBLIC_ORIGIN="" COOKIE_SECURE=false LOCAL_NODE_NAME="NAS CPU"
WORKDIR /app
COPY service/requirements.txt ./
RUN pip install -r requirements.txt \
    && python -c "import imageio_ffmpeg,os; os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), '/usr/local/bin/ffmpeg')" \
    && groupadd --gid 10001 atow \
    && useradd --uid 10001 --gid 10001 --create-home atow \
    && mkdir /data && chown 10001:10001 /data
COPY build-assets/models/ /opt/atow-models/
COPY service/app.py service/index.html service/remote_worker.py service/llm_refine.py ./
COPY deploy/nas/entrypoint.py /usr/local/bin/atow-entrypoint.py
LABEL org.opencontainers.image.title="Shengjian ARM64 NAS" \
    org.opencontainers.image.description="Offline audio transcription with history and timing for ARM64 NAS"
EXPOSE 8787
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import json,urllib.request,sys; sys.exit(not json.load(urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=3))['ready'])"
ENTRYPOINT ["python", "/usr/local/bin/atow-entrypoint.py"]
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8787", "--no-access-log", "--no-use-colors", "--limit-concurrency", "24"]
