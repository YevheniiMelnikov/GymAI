from django.urls import path

from .views import (
    ProfileAPIList,
    ProfileAPIUpdate,
    ProfileByTelegramIDView,
    ProfileAPIDestroy,
)

urlpatterns = [
    path("profiles/", ProfileAPIList.as_view(), name="profile_list"),
    path("profiles/<int:profile_id>/", ProfileAPIUpdate.as_view(), name="profile_update"),
    path("profiles/tg/<int:tg_id>/", ProfileByTelegramIDView.as_view(), name="profile_by_tg_id"),
    path("profiles/<int:pk>/delete/", ProfileAPIDestroy.as_view(), name="profile_delete"),
]
