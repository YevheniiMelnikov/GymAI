FROM python:3.13-slim

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME
ENV PYTHONPATH="/opt/common:$PYTHONPATH"
ENV TZ=Europe/Kyiv

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       python3-dev \
       curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -

ENV PATH="/root/.local/bin:$PATH"

RUN poetry --version

WORKDIR $APP_HOME

COPY pyproject.toml poetry.lock README.md $APP_HOME/

RUN poetry config virtualenvs.create false

RUN poetry install --no-interaction --no-ansi

COPY api $APP_HOME/api
COPY common /opt/common

WORKDIR $APP_HOME/api

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "-c", "echo 'Starting migrations...' && python manage.py migrate && echo 'Starting server...' && python manage.py runserver 0.0.0.0:8000"]
