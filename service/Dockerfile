FROM python:3.11-slim-bookworm
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=3 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN python -c "import imageio_ffmpeg,os; os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), '/usr/local/bin/ffmpeg')"
COPY app.py index.html remote_worker.py ./
RUN useradd --uid 10001 --create-home atow
USER 10001:10001
EXPOSE 8787
CMD ["uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8787", "--no-access-log", "--no-use-colors", "--limit-concurrency", "24"]
