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


class ClientNotFoundError(Exception):
    def __init__(self, profile_id: int):
        super().__init__(f"Client data not found for profile_id {profile_id}")
        self.profile_id = profile_id


class CoachNotFoundError(Exception):
    def __init__(self, profile_id: int):
        super().__init__(f"Coach data not found for profile_id {profile_id}")
        self.profile_id = profile_id


class SubscriptionNotFoundError(Exception):
    def __init__(self, profile_id: int):
        super().__init__(f"Subscription not found for profile_id {profile_id}")
        self.profile_id = profile_id


class ProgramNotFoundError(Exception):
    def __init__(self, profile_id: int):
        super().__init__(f"Program not found for profile_id {profile_id}")
        self.profile_id = profile_id


class PaymentNotFoundError(Exception):
    def __init__(self, profile_id: int):
        super().__init__(f"Payment not found for profile_id {profile_id}")
        self.profile_id = profile_id
