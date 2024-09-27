from django.urls import path
from .views import *

urlpatterns = [
    path("profiles/", ProfileAPIList.as_view(), name="profile_list"),
    path("profiles/<int:profile_id>/", ProfileAPIUpdate.as_view(), name="profile-update"),
    path("profiles/reset-tg/<int:profile_id>/", ResetTelegramIDView.as_view(), name="reset-tg"),
    path("profiles/tg/<int:telegram_id>/", ProfileByTelegramIDView.as_view(), name="profile-by-tg-id"),
    path("profiles/<int:id>/delete/", ProfileAPIDestroy.as_view(), name="profile-delete"),
    path("profiles/create/", CreateUserView.as_view(), name="profile-create"),
    path("profiles/<str:username>/", UserProfileView.as_view(), name="user-profile"),
    path("current-user/", CurrentUserView.as_view(), name="current-user"),
    path("client-profiles/", ClientProfileView.as_view(), name="client-profile-list"),
    path("client-profiles/<int:profile_id>/", ClientProfileUpdate.as_view(), name="client-profile-update"),
    path("coach-profiles/", CoachProfileView.as_view(), name="coach-profile-list"),
    path("coach-profiles/<int:profile_id>/", CoachProfileUpdate.as_view(), name="coach-profile-update"),
    path("get-user-token/", GetUserTokenView.as_view(), name="get-user-token"),
    path("send-feedback/", SendFeedbackAPIView.as_view(), name="send-feedback"),
    path("send-welcome-email/", SendWelcomeEmailAPIView.as_view(), name="send_welcome_email"),
]
