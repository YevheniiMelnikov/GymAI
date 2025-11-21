from django.urls import path

from .views import (
    ProfileAPIList,
    ProfileAPIUpdate,
    ProfileByTelegramIDView,
    ProfileAPIDestroy,
    ClientProfileList,
    ClientProfileUpdate,
    ClientProfileByProfile,
)

urlpatterns = [
    path("profiles/", ProfileAPIList.as_view(), name="profile_list"),
    path("profiles/<int:profile_id>/", ProfileAPIUpdate.as_view(), name="profile_update"),
    path("profiles/tg/<int:tg_id>/", ProfileByTelegramIDView.as_view(), name="profile_by_tg_id"),
    path("profiles/<int:pk>/delete/", ProfileAPIDestroy.as_view(), name="profile_delete"),
    path("client-profiles/", ClientProfileList.as_view(), name="client_profile_list"),
    path("client-profiles/<int:profile_id>/", ClientProfileUpdate.as_view(), name="client_profile_update"),
    path("client-profiles/pk/<int:pk>/", ClientProfileUpdate.as_view(), name="client_profile_update_pk"),  # <— NEW
    path(
        "client-profiles/by-profile/<int:profile_id>/",
        ClientProfileByProfile.as_view(),
        name="client_profile_by_profile",
    ),
]
