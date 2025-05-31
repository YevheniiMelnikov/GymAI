class UserServiceError(Exception):
    def __init__(self, message: str, code: int = 500, details: str = ""):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return f"Error {self.code}: {self.message} - {self.details}"


class ProfileNotFoundError(Exception):
    def __init__(self, tg_id: int):
        super().__init__(f"No current profile found for user {tg_id}")
        self.tg_id = tg_id
