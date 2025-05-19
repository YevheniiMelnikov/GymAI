from .payment_service import PaymentService
from .profile_service import ProfileService
from .workout_service import WorkoutService


class APIService:
    payment = PaymentService
    profile = ProfileService
    workout = WorkoutService
