class BaseSettings:  # pragma: no cover - minimal stub
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
