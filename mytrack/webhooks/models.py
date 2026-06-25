import secrets

from django.db import models


class WebhookEndpoint(models.Model):
    organisation = models.ForeignKey('tenancy.Organisation', on_delete=models.CASCADE, related_name='webhook_endpoints')
    url          = models.URLField(max_length=500)
    secret       = models.CharField(max_length=64, blank=True, help_text="HMAC-SHA256 signing secret")
    events       = models.JSONField(default=list)
    is_active    = models.BooleanField(default=True)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organisation} → {self.url}"

    def save(self, *args, **kwargs):
        if not self.secret:
            self.secret = secrets.token_hex(32)
        super().save(*args, **kwargs)


class WebhookDelivery(models.Model):
    endpoint    = models.ForeignKey(WebhookEndpoint, on_delete=models.CASCADE, related_name='deliveries')
    event_type  = models.CharField(max_length=60, db_index=True)
    payload     = models.JSONField()
    status_code = models.IntegerField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts    = models.IntegerField(default=0)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    error       = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
