import os

os.environ["TIME_ZONE"] = "Europe/Kyiv"

from .settings import *  # noqa

TIME_ZONE = "Europe/Kyiv"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    }
}
