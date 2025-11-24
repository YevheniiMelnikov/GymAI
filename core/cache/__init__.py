class _CacheProxy:
    @property
    def profile(self):
        from .profile import ProfileCacheManager

        return ProfileCacheManager

    @property
    def workout(self):
        from .workout import WorkoutCacheManager

        return WorkoutCacheManager

    @property
    def payment(self):
        from .payment import PaymentCacheManager

        return PaymentCacheManager


Cache = _CacheProxy()
