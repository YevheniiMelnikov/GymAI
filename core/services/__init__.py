class _APIServiceProxy:
    @property
    def payment(self):
        from .payment_service import PaymentService

        return PaymentService

    @property
    def profile(self):
        from .profile_service import ProfileService

        return ProfileService

    @property
    def workout(self):
        from .workout_service import WorkoutService

        return WorkoutService


APIService = _APIServiceProxy()
