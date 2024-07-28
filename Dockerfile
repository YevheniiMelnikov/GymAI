FROM python:3.12

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       python3-dev \
       wget \
       gnupg2 \
       lsb-release \
       ca-certificates

RUN wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && sh -c 'echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' \
    && apt-get update \
    && apt-get install -y postgresql-client-16 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR $APP_HOME

COPY requirements/requirements.txt $APP_HOME/requirements/requirements.txt
RUN pip install --no-cache-dir -r requirements/requirements.txt

COPY . $APP_HOME

RUN mkdir -p $APP_HOME/bot/backup/dumps

WORKDIR $APP_HOME/bot

EXPOSE 8000

CMD ["python", "main.py"]
