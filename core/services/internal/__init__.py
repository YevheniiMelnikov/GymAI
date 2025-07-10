class _APIServiceProxy:
    @property
    def payment(self):
        from core.services.internal.payment_service import PaymentService

        return PaymentService

    @property
    def profile(self):
        from core.services.internal.profile_service import ProfileService

        return ProfileService

    @property
    def workout(self):
        from core.services.internal.workout_service import WorkoutService

        return WorkoutService


APIService = _APIServiceProxy()
