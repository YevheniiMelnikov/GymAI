from accounts.views import PersonAPIList, PersonAPIUpdate, PersonAPIDetailView
from django.urls import path
from rest_framework.urlpatterns import format_suffix_patterns

urlpatterns = [
    path("persons_list/", PersonAPIList.as_view(), name="persons_list"),
    path("persons_list/<int:pk>", PersonAPIUpdate.as_view(), name="update_person"),
    path("persons_detail/<int:pk>", PersonAPIDetailView.as_view(), name="CRUD_person"),
]

urlpatterns = format_suffix_patterns(urlpatterns)
