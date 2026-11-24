from django.contrib import admin

from .models import Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "plan", "subscription_status", "created_at")
    list_filter = ("plan", "subscription_status")
    search_fields = ("name", "stripe_customer_id")
    inlines = (MembershipInline,)
