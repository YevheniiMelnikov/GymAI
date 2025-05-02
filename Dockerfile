FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml .
COPY uv.lock .
RUN pip install uv && uv pip install -r <(uv pip compile --quiet)

COPY . .

CMD ["python", "-u", "/app/bot/main.py"]
