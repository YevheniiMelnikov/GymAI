import types


def chain(*tasks):
    class _Result:
        def apply_async(self, *args, **kwargs):
            return types.SimpleNamespace(id="task-id")

    return _Result()
