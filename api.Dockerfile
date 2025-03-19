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
       git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY requirements.txt ./

RUN uv pip install --system -r requirements.txt

COPY api ./api
COPY common ./common

RUN python api/manage.py collectstatic --noinput

EXPOSE 8000

CMD ["bash", "-c", "python api/manage.py migrate && python api/manage.py runserver 0.0.0.0:8000"]
