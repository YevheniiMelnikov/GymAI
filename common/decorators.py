def singleton(cls):
    instances = {}

    class Wrapper(cls):
        def __new__(cls, *args, **kwargs):
            if cls not in instances:
                instances[cls] = super(Wrapper, cls).__new__(cls)
            return instances[cls]

    return Wrapper
