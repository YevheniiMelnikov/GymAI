class UsernameUnavailable(Exception):
    def __init__(self, username: str):
        super().__init__(f"Username {username} is already taken")
        self.username = username


class EmailUnavailable(Exception):
    def __init__(self, email: str):
        super().__init__(f"E-mail {email} is already taken")
        self.email = email


class UserServiceError(Exception):
    def __init__(self, message: str, code: int = 500, details: str = ""):
        self.message = message
        self.code = code
        self.details = details
        super().__init__(self.message)

    def __str__(self):
        return f"Error {self.code}: {self.message} - {self.details}"


class ProfileNotFoundError(Exception):
    def __init__(self, telegram_id: int):
        super().__init__(f"No current profile found for user {telegram_id}")
        self.telegram_id = telegram_id
