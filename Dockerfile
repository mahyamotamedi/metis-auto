# Local-development image for Metis-Auto (Stage 6). Readable, not production-hardened.
# Two targets:
#   runtime  pinned runtime dependencies (requirements.lock) + the package;
#            runs the walking skeleton. No test tools, no sample data.
#   dev      pinned dev dependencies (requirements-dev.lock) + the whole repo;
#            runs the test suite. Default target for compose.yaml.
# Secrets are never baked in: .env is excluded by .dockerignore and passed at
# run time (compose env_file). Guide: docs/guides/local_development.md.
#
# Base image pinned by digest (multi-arch OCI index: linux/amd64 + linux/arm64;
# python 3.13.16-slim-trixie), pulled and checked 2026-10-18. The tag is kept
# for readability; the digest decides. To update: `docker pull python:3.13-slim`,
# read the digest, rebuild, rerun the checks in docs/guides/local_development.md §6.

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    METIS_CONFIG_DIR=/app/config
WORKDIR /app
RUN useradd --create-home --uid 1000 metis \
    && mkdir -p /app/runs /app/data/spend \
    && chown -R metis /app

FROM base AS runtime
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
COPY scripts ./scripts
RUN pip install --no-deps .
USER metis
CMD ["python", "scripts/run_walking_skeleton.py"]

FROM base AS dev
COPY requirements-dev.lock ./
RUN pip install --require-hashes -r requirements-dev.lock
COPY --chown=metis . .
RUN pip install --no-deps -e .
USER metis
CMD ["python", "-m", "pytest", "-q"]
