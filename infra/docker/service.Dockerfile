# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ARG SERVICE_DIR
ARG SERVICE_EXTRAS=""
ARG HTTPCORE_WHEEL_URL="https://files.pythonhosted.org/packages/7e/f5/f66802a942d491edb555dd61e3a9961140fd64c90bce1eafd741609d334d/httpcore-1.0.9-py3-none-any.whl#sha256=2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=10
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV SERVICE_DIR=${SERVICE_DIR}

WORKDIR /app

COPY packages /app/packages
COPY data_foundation /app/data_foundation
COPY intelligence /app/intelligence
COPY runtime /app/runtime
COPY research /app/research
COPY frontend /app/frontend

RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --upgrade pip && \
    pip install "${HTTPCORE_WHEEL_URL}" && \
    pip install -e /app/packages/common -e "/app/${SERVICE_DIR}${SERVICE_EXTRAS}"
