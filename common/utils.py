from functools import wraps


def singleton(cls: type) -> object:
    instances = {}

    @wraps(cls)
    def get_instance(*args, **kwargs) -> object:
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance
