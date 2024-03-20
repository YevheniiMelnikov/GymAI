from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

from .views import RegisterUser

urlpatterns = [
    path("register/", RegisterUser.as_view(), name="register"),
]

urlpatterns = format_suffix_patterns(urlpatterns)
