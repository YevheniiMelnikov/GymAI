from accounts.views import PersonAPIView
from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

urlpatterns = [
    path("persons_list/", PersonAPIView.as_view(), name="persons_list"),
    path("persons_list/<int:id>", PersonAPIView.as_view(), name="update_person"),
]

urlpatterns = format_suffix_patterns(urlpatterns)
