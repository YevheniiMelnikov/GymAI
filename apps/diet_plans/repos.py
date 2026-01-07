from django.db.models import QuerySet

from apps.diet_plans.models import DietPlan


class DietPlanRepository:
    @staticmethod
    def base_qs() -> QuerySet[DietPlan]:  # pyrefly: ignore[bad-specialization]
        return DietPlan.objects.all().select_related("profile")  # type: ignore[return-value,missing-attribute]

    @staticmethod
    def get_all(profile_id: int) -> list[DietPlan]:
        return list(DietPlanRepository.base_qs().filter(profile_id=profile_id).order_by("-created_at"))

    @staticmethod
    def get_by_id(profile_id: int, plan_id: int) -> DietPlan | None:
        return DietPlanRepository.base_qs().filter(profile_id=profile_id, id=plan_id).first()

    @staticmethod
    def get_by_request_id(request_id: str) -> DietPlan | None:
        return DietPlanRepository.base_qs().filter(request_id=request_id).first()

    @staticmethod
    def create(
        *,
        profile_id: int,
        request_id: str,
        plan: dict,
    ) -> DietPlan:
        created = DietPlan.objects.create(profile_id=profile_id, request_id=request_id, plan=plan)
        return created
