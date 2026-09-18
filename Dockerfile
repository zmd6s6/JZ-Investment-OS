FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN pip install --no-cache-dir "uv==0.12.9" \
    && addgroup --system investment-os \
    && adduser --system --ingroup investment-os investment-os

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

RUN uv sync --frozen --no-dev \
    && chown -R investment-os:investment-os /app

USER investment-os

EXPOSE 8000

CMD ["uvicorn", "investment_os.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
