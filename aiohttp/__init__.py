class ClientSession:
    pass


class _Web:
    class Request: ...

    class Response: ...

    class Application: ...

    class AppRunner:
        async def setup(self) -> None: ...

    class TCPSite:
        def __init__(self, *args, **kwargs) -> None: ...
        async def start(self) -> None: ...

    @staticmethod
    def json_response(data: dict) -> dict:
        return data


web = _Web()
