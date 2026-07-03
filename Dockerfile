FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --shell /usr/sbin/nologin quant
COPY pyproject.toml README.md ./
COPY src ./src
COPY configs ./configs
RUN python -m pip install --no-cache-dir --upgrade pip && python -m pip install --no-cache-dir -e ".[cloud]"
USER quant
ENTRYPOINT ["quant-trade"]
CMD ["cloud", "run-job", "--config", "/app/configs/cloud/local_dry_run.yaml", "--job", "health_check"]
