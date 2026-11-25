from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from accounts.models import Membership, Organization
from documents.models import Document, DocumentRequest, Property, Vendor


def landing(request):
    return render(request, "core/landing.html", {"demo_enabled": settings.DEMO_MODE})


def pricing(request):
    return render(request, "core/pricing.html")


def demo_login(request):
    if request.method != "POST":
        return redirect("core:landing")
    if not settings.DEMO_MODE:
        messages.error(request, "The demo is currently disabled.")
        return redirect("core:landing")
    User = get_user_model()
    email = "demo@certdesk.app"
    user, created = User.objects.get_or_create(email=email, defaults={"username": email})
    if created:
        user.set_unusable_password()
        user.save()
    org = Organization.objects.filter(name="Northstar Property Demo").first()
    if not org:
        org = Organization.objects.create(
            name="Northstar Property Demo", plan="starter", subscription_status="demo"
        )
    Membership.objects.get_or_create(user=user, organization=org, defaults={"role": "owner"})
    seed_demo(org)
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return redirect("documents:dashboard")


def seed_demo(org):
    # The public demo is synthetic and intentionally reset on each demo login.
    for document in Document.objects.filter(organization=org):
        document.file.delete(save=False)
    org.document_requests.all().delete()
    org.properties.all().delete()
    org.vendors.all().delete()
    properties = [
        Property.objects.create(organization=org, name="Maple Court", address="124 Maple St, Austin, TX"),
        Property.objects.create(organization=org, name="Parkview Lofts", address="88 Park Ave, Austin, TX"),
    ]
    vendors = [
        Vendor.objects.create(organization=org, name="Bright Roof Co.", contact_name="Jamie Cole", email="jamie@brightroof.example", trade="Roofing"),
        Vendor.objects.create(organization=org, name="CleanRight LLC", contact_name="Morgan Lee", email="morgan@cleanright.example", trade="Cleaning"),
        Vendor.objects.create(organization=org, name="Ace Electric", contact_name="Taylor Reed", email="taylor@aceelectric.example", trade="Electrical"),
    ]
    items = [
        DocumentRequest.objects.create(organization=org, vendor=vendors[0], property=properties[0], document_type=DocumentRequest.TYPE_COI, due_date=timezone.localdate() - timedelta(days=3)),
        DocumentRequest.objects.create(organization=org, vendor=vendors[1], property=properties[1], document_type=DocumentRequest.TYPE_COI, due_date=timezone.localdate() + timedelta(days=18)),
        DocumentRequest.objects.create(organization=org, vendor=vendors[2], property=properties[0], document_type=DocumentRequest.TYPE_LICENSE, due_date=timezone.localdate() + timedelta(days=70)),
        DocumentRequest.objects.create(organization=org, vendor=vendors[2], property=properties[1], document_type=DocumentRequest.TYPE_COI, due_date=timezone.localdate() + timedelta(days=120)),
    ]
    from django.core.files.base import ContentFile

    Document.objects.create(
        organization=org,
        request=items[0],
        file=ContentFile(b"Demo expired certificate placeholder", name="bright-roof-general-liability.pdf"),
        original_filename="bright-roof-general-liability.pdf",
        carrier="Travelers",
        policy_number="GL-1102384",
        coverage="General Liability",
        expires_on=timezone.localdate() - timedelta(days=3),
    )
    Document.objects.create(
        organization=org,
        request=items[1],
        file=ContentFile(b"Demo certificate placeholder", name="cleanright-general-liability.pdf"),
        original_filename="cleanright-general-liability.pdf",
        carrier="Travelers",
        policy_number="GL-4829012",
        coverage="General Liability",
        expires_on=timezone.localdate() + timedelta(days=18),
    )
    Document.objects.create(
        organization=org,
        request=items[2],
        file=ContentFile(b"Demo license placeholder", name="ace-electric-license.pdf"),
        original_filename="ace-electric-license.pdf",
        carrier="Texas Electrical Licensing",
        policy_number="TX-90144",
        coverage="Electrical License",
        expires_on=timezone.localdate() + timedelta(days=70),
    )


def legal(request):
    return render(request, "core/legal.html")


def health(request):
    from django.http import JsonResponse

    return JsonResponse({"status": "ok"})


@login_required
@require_POST
def stripe_checkout(request):
    membership = Membership.objects.filter(user=request.user).select_related("organization").first()
    if not membership:
        return redirect("accounts:signup")
    plan = request.POST.get("plan", Organization.PLAN_STARTER)
    price_id = {
        Organization.PLAN_STARTER: settings.STRIPE_STARTER_PRICE_ID,
        Organization.PLAN_GROWTH: settings.STRIPE_GROWTH_PRICE_ID,
    }.get(plan)
    if plan not in dict(Organization.PLAN_CHOICES):
        messages.error(request, "Choose a valid plan.")
        return redirect("core:pricing")
    if not settings.STRIPE_SECRET_KEY or not price_id:
        messages.info(request, "Stripe is not configured yet. Add the price IDs in .env to enable checkout.")
        return redirect("core:pricing")
    import stripe

    stripe.api_key = settings.STRIPE_SECRET_KEY
    customer = membership.organization.stripe_customer_id
    checkout_params = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "client_reference_id": str(membership.organization.pk),
        "metadata": {"organization_id": str(membership.organization.pk), "plan": plan},
        "subscription_data": {
            "metadata": {"organization_id": str(membership.organization.pk), "plan": plan}
        },
        "success_url": f"{settings.BASE_URL}/dashboard/?checkout=success",
        "cancel_url": f"{settings.BASE_URL}/pricing/?checkout=canceled",
    }
    if customer:
        checkout_params["customer"] = customer
    else:
        checkout_params["customer_email"] = membership.user.email
    session = stripe.checkout.Session.create(**checkout_params)
    return redirect(session.url)


def _stripe_object_id(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("id", "")
    return getattr(value, "id", "") or ""


def _stripe_subscription_id(invoice):
    subscription = invoice.get("subscription")
    if not subscription:
        subscription = (
            invoice.get("parent", {})
            .get("subscription_details", {})
            .get("subscription")
        )
    return _stripe_object_id(subscription)


def _stripe_plan_for_price(price_id):
    if price_id and price_id == settings.STRIPE_STARTER_PRICE_ID:
        return Organization.PLAN_STARTER
    if price_id and price_id == settings.STRIPE_GROWTH_PRICE_ID:
        return Organization.PLAN_GROWTH
    return None


def _stripe_organization(subscription=None, customer_id="", subscription_id=""):
    metadata = subscription.get("metadata", {}) if subscription else {}
    organization_id = metadata.get("organization_id")
    queryset = Organization.objects.all()
    if organization_id:
        organization = queryset.filter(pk=organization_id).first()
        if organization:
            return organization
    if subscription_id:
        organization = queryset.filter(stripe_subscription_id=subscription_id).first()
        if organization:
            return organization
    if customer_id:
        return queryset.filter(stripe_customer_id=customer_id).first()
    return None


def _sync_stripe_subscription(subscription):
    subscription_id = _stripe_object_id(subscription)
    customer_id = _stripe_object_id(subscription.get("customer"))
    organization = _stripe_organization(
        subscription=subscription,
        customer_id=customer_id,
        subscription_id=subscription_id,
    )
    if not organization:
        return

    price_id = ""
    items = subscription.get("items", {}).get("data", [])
    if items:
        price_id = items[0].get("price", {}).get("id", "")
    plan = _stripe_plan_for_price(price_id)
    status = "canceling" if subscription.get("cancel_at_period_end") else subscription.get("status", "")
    updates = {
        "subscription_status": status,
        "stripe_customer_id": customer_id,
        "stripe_subscription_id": subscription_id,
    }
    if plan:
        updates["plan"] = plan
    organization.__class__.objects.filter(pk=organization.pk).update(**updates)


@csrf_exempt
def stripe_webhook(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    if not settings.STRIPE_WEBHOOK_SECRET or not settings.STRIPE_SECRET_KEY:
        return JsonResponse({"error": "Stripe webhook is not configured"}, status=503)

    import stripe

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            request.body, signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        return JsonResponse({"error": "Invalid webhook signature"}, status=400)

    event_type = event.get("type", "")
    event_object = event.get("data", {}).get("object", {})
    if event_type == "checkout.session.completed":
        organization = _stripe_organization(
            subscription={"metadata": event_object.get("metadata", {})},
            customer_id=_stripe_object_id(event_object.get("customer")),
            subscription_id=_stripe_object_id(event_object.get("subscription")),
        )
        if organization:
            plan = event_object.get("metadata", {}).get("plan")
            updates = {
                "subscription_status": "active",
                "stripe_customer_id": _stripe_object_id(event_object.get("customer")),
                "stripe_subscription_id": _stripe_object_id(event_object.get("subscription")),
            }
            if plan in dict(Organization.PLAN_CHOICES):
                updates["plan"] = plan
            Organization.objects.filter(pk=organization.pk).update(**updates)
    elif event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        _sync_stripe_subscription(event_object)
    elif event_type in {"invoice.paid", "invoice.payment_failed"}:
        subscription_id = _stripe_subscription_id(event_object)
        customer_id = _stripe_object_id(event_object.get("customer"))
        organization = _stripe_organization(
            customer_id=customer_id,
            subscription_id=subscription_id,
        )
        if organization:
            status = "active" if event_type == "invoice.paid" else "past_due"
            updates = {"subscription_status": status}
            if customer_id:
                updates["stripe_customer_id"] = customer_id
            if subscription_id:
                updates["stripe_subscription_id"] = subscription_id
            Organization.objects.filter(pk=organization.pk).update(**updates)

    return JsonResponse({"received": True, "type": event_type}, status=200)
