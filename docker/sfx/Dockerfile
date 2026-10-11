FROM python:3.12-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/srv/models/huggingface \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 SFX_WORKER_EMBEDDED=0
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 git \
    && rm -rf /var/lib/apt/lists/*
# Inference dependencies belong to this image only; the game server stays lightweight.
RUN pip install --no-cache-dir torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cpu
COPY docker/sfx/requirements.txt /tmp/sfx-requirements.txt
RUN pip install --no-cache-dir -r /tmp/sfx-requirements.txt
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip python -c "import subprocess,tomllib; subprocess.check_call(['pip','install',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])"
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .
CMD ["python", "-m", "app.sfx"]
