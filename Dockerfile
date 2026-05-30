FROM erispulse/erispulse:latest

LABEL org.opencontainers.image.title="ErisPulse-CYOA" \
      org.opencontainers.image.description="互动小说播放器 — 基于 Ink 的多平台故事引擎" \
      org.opencontainers.image.url="https://github.com/ErisPulse/ErisPulse-CYOA" \
      org.opencontainers.image.source="https://github.com/ErisPulse/ErisPulse-CYOA"

COPY pyproject.toml README.md ./
COPY CYOA/ ./CYOA/

RUN uv pip install --system -e .
