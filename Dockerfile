FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir .
EXPOSE 4242
ENV CODEX_PROXY_API_KEY=""
ENV CODEX_PROXY_BASE_URL=""
CMD ["codex-proxy"]
