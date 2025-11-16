from . import canvas
from . import signals
from .canvas import chain


class Celery:
    def __init__(self, *args, **kwargs):
        self.tasks = {}
        self.conf = {}

    def task(self, *args, **kwargs):
        def decorator(func):
            self.tasks[func.__name__] = func
            return func

        return decorator

    def autodiscover_tasks(self, *args, **kwargs):
        return None


class Task:
    ...


__all__ = ["Celery", "Task", "signals", "chain", "canvas"]
