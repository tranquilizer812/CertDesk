import uuid

from django.conf import settings
from django.db import models


class Organization(models.Model):
    PLAN_STARTER = "starter"
    PLAN_GROWTH = "growth"
    PLAN_CHOICES = [(PLAN_STARTER, "Starter"), (PLAN_GROWTH, "Growth")]

    name = models.CharField(max_length=160)
    slug = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default=PLAN_STARTER)
    subscription_status = models.CharField(max_length=30, default="trialing")
    stripe_customer_id = models.CharField(max_length=255, blank=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def document_limit(self):
        return 75 if self.plan == self.PLAN_STARTER else 200

    @property
    def is_demo(self):
        return self.name == "Northstar Property Demo"

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLE_OWNER = "owner"
    ROLE_ADMIN = "admin"
    ROLE_MEMBER = "member"
    ROLE_CHOICES = [
        (ROLE_OWNER, "Owner"),
        (ROLE_ADMIN, "Administrator"),
        (ROLE_MEMBER, "Member"),
    ]

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "user"], name="unique_org_member")
        ]

    def __str__(self):
        return f"{self.user} · {self.organization} ({self.role})"
