from config.app_settings import normalize_service_host


def test_normalize_service_host_preserves_credentials() -> None:
    original = "amqp://user:pass@localhost:5672/"
    result = normalize_service_host(original, "rabbitmq", default_scheme="amqp")
    assert result == "amqp://user:pass@rabbitmq:5672/"


def test_normalize_service_host_handles_hostless_url() -> None:
    original = "localhost:9000/internal"
    result = normalize_service_host(original, "ai_coach")
    assert result == "http://ai_coach:9000/internal"


def test_normalize_service_host_keeps_existing_host() -> None:
    original = "http://api:8080/"
    result = normalize_service_host(original, "ai_coach")
    assert result == original


def test_normalize_service_host_forces_override() -> None:
    original = "http://api:8080/"
    result = normalize_service_host(original, "bot", force=True)
    assert result == "http://bot:8080/"
