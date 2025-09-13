from core.containers import create_container, set_container
from core.infra.payment_repository import HTTPPaymentRepository
from core.infra.profile_repository import HTTPProfileRepository
from core.payment import PaymentProcessor


def test_container_provides_payment_processor() -> None:
    container = create_container()
    set_container(container)
    client = container.http_client()
    processor = container.payment_processor()
    assert isinstance(processor, PaymentProcessor)
    assert isinstance(processor.payment_service._repository, HTTPPaymentRepository)
    assert isinstance(processor.profile_service._repository, HTTPProfileRepository)
    assert not client.is_closed
    container.http_client.shutdown()
    assert client.is_closed
