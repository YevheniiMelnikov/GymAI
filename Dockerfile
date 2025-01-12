FROM python:3.13-slim

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME
ENV TZ=Europe/Kyiv

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
    && rm -rf /var/lib/apt/lists/*

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y postgresql-client-16 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="/root/.local/bin:$PATH"

RUN poetry --version

WORKDIR $APP_HOME

COPY pyproject.toml poetry.lock README.md $APP_HOME/

RUN poetry config virtualenvs.create false

RUN poetry install --no-interaction --no-ansi --no-root

COPY . $APP_HOME

RUN mkdir -p $APP_HOME/bot/backup/dumps

WORKDIR $APP_HOME/bot

EXPOSE 8000

CMD ["python", "main.py"]