from loguru import logger

from apps.metrics.models import MetricsEvent
from core.metrics.constants import METRICS_EVENT_TYPES, METRICS_SOURCES


def record_event(event_type: str, source: str, source_id: str) -> bool:
    try:
        if event_type not in METRICS_EVENT_TYPES:
            logger.warning(f"metrics_event_invalid type={event_type}")
            return False
        if source not in METRICS_SOURCES:
            logger.warning(f"metrics_event_invalid source={source}")
            return False
        if not source_id:
            logger.warning("metrics_event_invalid source_id=empty")
            return False
        _, created = MetricsEvent.objects.get_or_create(
            event_type=event_type,
            source=source,
            source_id=str(source_id),
        )
        return created
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"metrics_event_failed type={event_type} error={exc}")
        return False
