from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from documents.models import DocumentRequest, ReminderLog, UploadToken


class Command(BaseCommand):
    help = "Email vendors about missing documents and documents expiring within the configured window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        today = timezone.localdate()
        cutoff = today + timedelta(days=options["days"])
        sent = 0
        for item in DocumentRequest.objects.select_related("vendor", "organization"):
            document = item.latest_document
            kind = None
            if not document and item.due_date and item.due_date <= cutoff:
                kind = "missing"
            elif document and document.expires_on and document.expires_on <= cutoff:
                kind = "expired" if document.expires_on < today else "expiring"
            if not kind:
                continue
            if ReminderLog.objects.filter(request=item, sent_on=today).exists():
                continue
            if options["dry_run"]:
                self.stdout.write(f"Would email {item.vendor.email}: {item} ({kind})")
                continue
            reminder, created = ReminderLog.objects.get_or_create(
                request=item,
                sent_on=today,
                defaults={"organization": item.organization, "kind": kind},
            )
            if not created:
                continue
            token = None
            if kind == "missing":
                subject = f"Document still needed: {item.get_document_type_display()}"
                upload_url = ""
                if not options["dry_run"]:
                    token = UploadToken.objects.create(
                        request=item, expires_at=timezone.now() + timedelta(days=7)
                    )
                    upload_url = f"{settings.BASE_URL.rstrip('/')}{token.get_absolute_url()}"
                body = (
                    f"Hello {item.vendor.contact_name or item.vendor.name},\n\n"
                    f"We still need your {item.get_document_type_display()}"
                    f"{f' (due {item.due_date:%B %d, %Y})' if item.due_date else ''}.\n\n"
                    f"Please upload it using this secure link:\n{upload_url}\n\n"
                    "The link expires in 7 days and can be used once."
                )
            else:
                days = (document.expires_on - today).days
                subject = f"Document expiration reminder: {item.get_document_type_display()}"
                body = (
                    f"Hello {item.vendor.contact_name or item.vendor.name},\n\n"
                    f"Your {item.get_document_type_display()} expired or expires on "
                    f"{document.expires_on:%B %d, %Y} "
                    f"({days} day{'s' if days != 1 else ''} from today).\n\n"
                    "Please send the current document to your property manager."
                )
            try:
                delivered = send_mail(
                    subject, body, None, [item.vendor.email], fail_silently=False
                )
            except Exception:
                reminder.delete()
                if token is not None:
                    token.delete()
                raise CommandError(
                    f"Could not send the reminder for request {item.pk}; no email link was issued."
                ) from None
            if delivered != 1:
                reminder.delete()
                if token is not None:
                    token.delete()
                raise CommandError(
                    f"Could not send the reminder for request {item.pk}; no email link was issued."
                )
            sent += 1
        self.stdout.write(self.style.SUCCESS(f"Sent {sent} document reminder(s)."))
