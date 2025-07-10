from django.urls import path
from .views import PaymentCreateView, PaymentListView, PaymentDetailView

urlpatterns = [
    path("payments/create/", PaymentCreateView.as_view(), name="payments-create"),
    path("payments/", PaymentListView.as_view(), name="payments-list"),
    path("payments/<int:pk>/", PaymentDetailView.as_view(), name="payments-update"),
]
