from .payment import PaymentCacheManager
from .profile import ProfileCacheManager
from .client_profile import ClientCacheManager
from .coach_profile import CoachCacheManager
from .workout import WorkoutCacheManager


class Cache:
    profile = ProfileCacheManager
    client = ClientCacheManager
    coach = CoachCacheManager
    workout = WorkoutCacheManager
    payment = PaymentCacheManager
