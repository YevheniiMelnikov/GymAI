class _Logger:
    def debug(self, *args, **kwargs):
        pass

    info = warning = error = exception = success = remove = configure = debug


logger = _Logger()
