def singleton(cls):
    instances = {}

    class Wrapper(cls):
        def __new__(inner_cls, *args, **kwargs):
            if cls not in instances:
                instances[cls] = super(cls, inner_cls).__new__(cls)
                cls.__init__(instances[cls], *args, **kwargs)
            return instances[cls]

    Wrapper.__name__ = cls.__name__
    Wrapper.__module__ = cls.__module__
    return Wrapper
