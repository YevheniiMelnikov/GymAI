FROM python:3.12

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc \
       python3-dev \
       wget \
       gnupg2

RUN sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list' \
    && wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add - \
    && apt-get update \
    && apt-get install -y postgresql-client-16 \
    && apt-get clean

WORKDIR $APP_HOME

ADD requirements/requirements.txt $APP_HOME/requirements/requirements.txt
ADD bot $APP_HOME/bot
RUN pip install -r requirements/requirements.txt

WORKDIR $APP_HOME/bot

EXPOSE 8000