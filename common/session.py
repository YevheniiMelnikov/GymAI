class UserSession:
    def __init__(self):
        self._current_user = None
        self._auth_token = None

    def set_user(self, user, auth_token):
        self._current_user = user
        self._auth_token = auth_token

    def get_user(self):
        return self._current_user

    def get_auth_token(self):
        return self._auth_token
