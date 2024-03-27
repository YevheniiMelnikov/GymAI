FROM python:3.12

ENV APP_HOME=/opt
ENV PYTHONPATH=$APP_HOME

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev

WORKDIR $APP_HOME

ADD requirements/requirements.txt $APP_HOME/requirements/requirements.txt
ADD bot $APP_HOME/bot
RUN pip install -r requirements/requirements.txt

WORKDIR $APP_HOME/bot

EXPOSE 8000