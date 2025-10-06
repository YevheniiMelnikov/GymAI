from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from celery import Celery
from kombu import Connection, Exchange, Producer, Queue
from kombu.exceptions import ChannelError
from loguru import logger


def _parse_broker(broker_url: str) -> tuple[str, str, str]:
    parsed = urlparse(broker_url)
    vhost = parsed.path or "/"
    host = parsed.hostname or ""
    netloc = parsed.netloc
    scheme_host = f"{parsed.scheme}://{host}" if parsed.scheme else host
    return scheme_host, vhost, netloc


def trace_publish(
    app: Celery,
    *,
    queue_name: str,
    exchange_name: str,
    routing_key: str,
    task_name: str,
    payload: dict[str, Any],
) -> str:
    broker_url_obj = getattr(app.conf, "broker_url", None)
    broker_url: str = str(broker_url_obj or "")
    result_backend_obj = getattr(app.conf, "result_backend", None)
    result_backend: str = str(result_backend_obj or "")

    scheme_host, vhost, netloc = _parse_broker(broker_url)
    logger.info(
        f"[TRACE] broker_url={broker_url} scheme_host={scheme_host} vhost={vhost} "
        f"netloc={netloc} backend={result_backend}"
    )

    exchange = Exchange(exchange_name, type="direct", durable=True)
    queue = Queue(queue_name, exchange=exchange, routing_key=routing_key, durable=True)

    before_messages = -1
    before_consumers = -1
    after_messages = -1
    after_consumers = -1

    unroutable: dict[str, Any] = {"flag": False, "reply_code": None, "reply_text": None}

    try:
        with Connection(broker_url) as connection:
            channel = connection.channel()
            try:
                declaration = channel.queue_declare(queue=queue_name, passive=True)
                before_messages = declaration.message_count
                before_consumers = declaration.consumer_count
            except ChannelError as exc:
                logger.error(f"[TRACE] passive declare failed queue={queue_name}: {exc!s}")

            def _on_return(_: Exception, message: Any) -> None:
                unroutable["flag"] = True
                unroutable["reply_code"] = getattr(message, "reply_code", None)
                unroutable["reply_text"] = getattr(message, "reply_text", None)

            producer = Producer(channel, exchange=exchange, on_return=_on_return)
            producer.publish(
                {"probe": True},
                routing_key=routing_key,
                declare=[queue],
                mandatory=True,
                retry=True,
                retry_policy={"max_retries": 1, "interval_start": 0, "interval_step": 0.2},
            )
            channel.close()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[TRACE] probe publish error: {exc!s}")

    if unroutable["flag"]:
        logger.error(
            f"[TRACE] mandatory return exchange={exchange_name} routing_key={routing_key} "
            f"code={unroutable['reply_code']} text={unroutable['reply_text']}"
        )

    async_result = app.send_task(
        task_name,
        args=(payload,),
        queue=queue_name,
        routing_key=routing_key,
    )
    task_id = async_result.id
    logger.info(f"[TRACE] send_task name={task_name} queue={queue_name} routing_key={routing_key} task_id={task_id}")

    try:
        with Connection(broker_url) as connection:
            channel = connection.channel()
            try:
                declaration = channel.queue_declare(queue=queue_name, passive=True)
                after_messages = declaration.message_count
                after_consumers = declaration.consumer_count
            except ChannelError as exc:
                logger.error(f"[TRACE] passive declare (after) failed queue={queue_name}: {exc!s}")
            channel.close()
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[TRACE] post declare error: {exc!s}")

    logger.info(
        f"[TRACE] depth queue={queue_name} before messages={before_messages} consumers={before_consumers} "
        f"after messages={after_messages} consumers={after_consumers}"
    )

    try:
        inspector = app.control.inspect()
        active_queues = inspector.active_queues() if inspector else None
        registered = inspector.registered() if inspector else None
        logger.info(f"[TRACE] inspect.active_queues={json.dumps(active_queues or {}, ensure_ascii=False)}")
        logger.info(f"[TRACE] inspect.registered={json.dumps(registered or {}, ensure_ascii=False)}")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[TRACE] inspect failed: {exc!s}")

    return task_id


__all__ = ["trace_publish"]
