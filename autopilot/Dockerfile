# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN python -m pip install --no-cache-dir --no-compile . \
    && rm -rf /root/.cache

RUN mkdir -p /data /scratch \
    && chown -R 10001:10001 /data /scratch /app

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "danmu_autopilot.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test

USER root
COPY tests ./tests
RUN python -m pip install --no-cache-dir --no-compile '.[test]' \
    && rm -rf /root/.cache
USER 10001:10001
CMD ["python", "-m", "pytest", "-q"]

