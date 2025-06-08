import pytest
from rest_framework.test import APIRequestFactory
from rest_framework_api_key.models import APIKey

from apps.payments.models import Payment
from apps.payments.views import PaymentListView
from apps.profiles.models import Profile, ClientProfile


import os


@pytest.mark.skip(reason="SQLite test DB lacks postgres features")
@pytest.mark.django_db
def test_payment_list_filters():
    factory = APIRequestFactory()
    api_key, key = APIKey.objects.create_key(name="test")

    profile = Profile.objects.create(tg_id=1, status="client")
    client = ClientProfile.objects.create(profile=profile)
    Payment.objects.create(payment_type="sub", client_profile=client, order_id="1", amount=10, status="success")
    Payment.objects.create(payment_type="sub", client_profile=client, order_id="2", amount=20, status="pending")

    request = factory.get("/payments/", {"status": "success"}, HTTP_AUTHORIZATION=f"Api-Key {key}")
    response = PaymentListView.as_view()(request)
    assert response.status_code == 200
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["order_id"] == "1"

