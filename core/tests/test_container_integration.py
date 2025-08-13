import pytest

from core.containers import create_container, set_container
from core.infra.payment_repository import HTTPPaymentRepository
from core.infra.profile_repository import HTTPProfileRepository
from core.payment_processor import PaymentProcessor


@pytest.mark.asyncio
async def test_container_provides_payment_processor() -> None:
    container = create_container()
    set_container(container)
    client = await container.http_client()  # pyrefly: ignore[async-error]
    processor = await container.payment_processor()  # pyrefly: ignore[async-error]
    assert isinstance(processor, PaymentProcessor)
    assert isinstance(processor.payment_service._repository, HTTPPaymentRepository)
    assert isinstance(processor.profile_service._repository, HTTPProfileRepository)
    assert not client.is_closed
    await container.http_client.shutdown()  # pyrefly: ignore[async-error]
    assert client.is_closed
