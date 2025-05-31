from django.db import models

from apps.profiles.models import Profile


class Payment(models.Model):
    payment_type = models.CharField(max_length=50)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="payments")
    order_id = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=50, default="PENDING")  # liqpay status
    payout_handled = models.BooleanField(default=False)  # coach notified
    processed = models.BooleanField(default=False)  # client notified
    error = models.CharField(max_length=250, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment"
        verbose_name_plural = "Payments"
        app_label = "apps.payments"
