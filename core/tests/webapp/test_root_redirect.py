import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.http import HttpResponse
from django.test import Client

django.setup()


def test_root_redirects_to_webapp() -> None:
    client: Client = Client()
    resp: HttpResponse = client.get("/?type=program", HTTP_HOST="localhost")
    assert resp.status_code in (301, 302)
    assert resp["Location"].endswith("/webapp/?type=program")
