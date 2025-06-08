import os

env_defaults = {
        'API_KEY': 'test_api_key',
        'API_URL': 'http://localhost/',
        'BOT_TOKEN': 'bot_token',
        'BOT_LINK': 'http://bot',
        'WEBHOOK_HOST': 'http://localhost',
        'WEBHOOK_PORT': '8000',
        'GOOGLE_APPLICATION_CREDENTIALS': '/tmp/creds.json',
        'SPREADSHEET_ID': 'sheet',
        'TG_SUPPORT_CONTACT': '@support',
        'PUBLIC_OFFER': 'http://offer',
        'PRIVACY_POLICY': 'http://privacy',
        'EMAIL': 'test@example.com',
        'ADMIN_ID': '1',
        'PAYMENT_PRIVATE_KEY': 'priv',
        'PAYMENT_PUB_KEY': 'pub',
        'CHECKOUT_URL': 'http://checkout',
        'POSTGRES_PASSWORD': 'password',
    }
for key, value in env_defaults.items():
    os.environ.setdefault(key, value)
os.environ['TIME_ZONE'] = 'Europe/Kyiv'
os.environ['PAYMENT_PRIVATE_KEY'] = 'priv'

def pytest_configure():
    pass


import pytest
from django.core.management import call_command


@pytest.fixture(autouse=True, scope="session")
def apply_migrations(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("migrate", run_syncdb=True, verbosity=0)


@pytest.fixture(autouse=True, scope="session")
def create_tables(django_db_setup, django_db_blocker):
    from django.db import connection
    from apps.profiles.models import Profile, ClientProfile, CoachProfile
    from apps.payments.models import Payment

    with django_db_blocker.unblock():
        with connection.schema_editor() as editor:
            for model in (Profile, ClientProfile, CoachProfile, Payment):
                editor.create_model(model)


import pytest
