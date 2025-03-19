FROM python:3.13-slim

ENV APP_HOME=/app
ENV PYTHONPATH=$APP_HOME:/app/common
ENV TZ=Europe/Kyiv

WORKDIR $APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       python3-dev \
       wget \
       curl \
       gnupg2 \
       lsb-release \
       ca-certificates \
       redis-tools \
       git \
    && rm -rf /var/lib/apt/lists/*

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y postgresql-client-17 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY requirements.txt ./

RUN uv pip install --system -r requirements.txt

COPY . .
COPY common ./common

RUN mkdir -p bot/backup/dumps

EXPOSE 8000

CMD ["python", "bot/main.py"]
