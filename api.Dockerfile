FROM python:3.13-slim

ARG INSTALL_DEV=false
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .
RUN pip install uv && uv pip install -r <(uv pip compile --quiet)

COPY . .
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
