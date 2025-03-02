FROM python:3.13-slim

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME:/opt/common
ENV TZ=Europe/Kyiv

WORKDIR $APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       python3-dev \
       curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="/root/.local/bin:$PATH"
RUN poetry --version

COPY pyproject.toml poetry.lock README.md ./
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi

COPY api ./api
COPY common ./common

RUN python api/manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "-c", "python api/manage.py migrate && python api/manage.py runserver 0.0.0.0:8000"]
