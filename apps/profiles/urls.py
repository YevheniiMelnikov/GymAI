from django.urls import path
from .views import (
    ProfileAPIList,
    ProfileAPIUpdate,
    ProfileByTelegramIDView,
    ProfileAPIDestroy,
    CoachProfileView,
    CoachProfileUpdate,
    ClientProfileView,
    ClientProfileUpdate,
)

urlpatterns = [
    path("profiles/", ProfileAPIList.as_view(), name="profile_list"),
    path("profiles/<int:profile_id>/", ProfileAPIUpdate.as_view(), name="profile_update"),
    path("profiles/tg/<int:telegram_id>/", ProfileByTelegramIDView.as_view(), name="profile_by_tg_id"),
    path("profiles/<int:id>/delete/", ProfileAPIDestroy.as_view(), name="profile_delete"),
    path("client-profiles/", ClientProfileView.as_view(), name="client_profile_list"),
    path("client-profiles/<int:profile_id>/", ClientProfileUpdate.as_view(), name="client_profile_update"),
    path("coach-profiles/", CoachProfileView.as_view(), name="coach_profile_list"),
    path("coach-profiles/<int:profile_id>/", CoachProfileUpdate.as_view(), name="coach_profile_update"),
]
