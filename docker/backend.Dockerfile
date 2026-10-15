FROM python:3.11-slim-bookworm AS dependencies
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 UV_COMPILE_BYTECODE=1
RUN sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv && pip install --no-cache-dir uv==0.9.5 --index-url "$PIP_INDEX_URL"
COPY docker/requirements.lock /tmp/requirements.lock
RUN uv pip install --python /opt/venv/bin/python --index-url "$PIP_INDEX_URL" --require-hashes \
    -r /tmp/requirements.lock

FROM python:3.11-slim-bookworm AS runtime
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DOCKER=true LOGGING_PROFILE=docker TZ=Asia/Shanghai
RUN sed -i "s|http://deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 update \
    && apt-get -o Acquire::Retries=2 -o Acquire::http::Timeout=30 install -y --no-install-recommends \
    ca-certificates curl libglib2.0-0 libpango-1.0-0 libpangoft2-1.0-0 \
    libharfbuzz-subset0 fonts-noto-cjk pandoc tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dependencies /opt/venv /opt/venv
WORKDIR /app
COPY . .
ARG SOURCE_COMMIT=unknown
RUN SOURCE_COMMIT="$SOURCE_COMMIT" python docker/write_build_info.py \
    && mkdir -p /app/logs /app/data /app/runtime
LABEL org.opencontainers.image.source="https://github.com/Arser/TradingAgents-CN" \
    org.opencontainers.image.revision="$SOURCE_COMMIT"
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
