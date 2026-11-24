# CertDesk

CertDesk is a focused micro-SaaS for small property-management teams to collect vendor documents, track expiration dates, chase renewals, and export a clean audit record.

> CertDesk records document presence and expiration dates. It does not determine whether insurance coverage is legally or commercially sufficient and does not provide legal advice.

## What is included

- Landing page, pricing, legal/product-boundary page
- Email/password workspaces with owner membership
- Vendor, property, and document-request management
- Status model: active, expiring within 30 days, expired, missing
- Internal uploads and one-use vendor upload links (7-day expiry), with a 10 MB PDF/image upload limit
- CSV imports with a 5 MB file limit
- Vendor link delivery by email
- Optional AI-assisted metadata extraction with employee review before details are applied
- CSV import and export with plan-limit enforcement and spreadsheet-formula protection
- Expiration reminder management command
- Stripe Checkout and webhook synchronization (optional), including cancellation and payment-failure states
- SQLite for local use; PostgreSQL supported for production
- Responsive UI with a synthetic seeded demo workspace

## Quick start (Windows)

```powershell
cd C:\CertDesk
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

Open <http://127.0.0.1:8000/> and choose **Explore the live demo**.

The local email backend prints email messages in the server console. The demo login creates a synthetic workspace; it does not require an email provider.

## Configuration

Edit `C:\CertDesk\.env`:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Required in production; use a long random value |
| `DEBUG` | Set `False` in production |
| `ALLOWED_HOSTS` | Comma-separated deployed hostnames |
| `CSRF_TRUSTED_ORIGINS` | Full HTTPS origins used by the deployment |
| `SESSION_COOKIE_SECURE` | Send session cookies only over HTTPS; defaults to `True` when `DEBUG=False` |
| `CSRF_COOKIE_SECURE` | Send CSRF cookies only over HTTPS; defaults to `True` when `DEBUG=False` |
| `SECURE_SSL_REDIRECT` | Redirect HTTP to HTTPS; defaults to `True` when `DEBUG=False` |
| `SECURE_HSTS_SECONDS` | HSTS lifetime in seconds; use `0` to disable |
| `BASE_URL` | Public origin, e.g. `https://certdesk.example` |
| `MEDIA_ROOT` | Optional absolute path for durable uploaded files |
| `DATABASE_URL` | PostgreSQL URL in production; blank uses SQLite reliably |
| `EMAIL_BACKEND` | SMTP/API email backend in production |
| `STRIPE_SECRET_KEY` | Stripe secret API key |
| `STRIPE_WEBHOOK_SECRET` | Signing secret for the webhook endpoint |
| `STRIPE_STARTER_PRICE_ID` | Recurring Stripe Price for Starter ($29) |
| `STRIPE_GROWTH_PRICE_ID` | Recurring Stripe Price for Growth ($49) |
| `AI_BASE_URL` | Optional OpenAI-compatible API root or full `/chat/completions` URL |
| `AI_API_KEY` | Optional API key for the configured AI provider |
| `AI_MODEL` | Optional vision-capable model name |
| `AI_TIMEOUT_SECONDS` | Provider request timeout; defaults to 30 seconds |
| `DEMO_MODE` | Set `False` on the public production deployment |

## Optional AI-assisted metadata extraction

Set `AI_BASE_URL`, `AI_API_KEY`, and `AI_MODEL` to enable employee-triggered extraction for Growth workspaces. The feature extracts the carrier, policy number, coverage, and expiration date from an uploaded PDF or image. The provider must expose an OpenAI-compatible Chat Completions endpoint and support the configured model.

A workspace employee requests extraction explicitly from the document detail page. The app sends only the file to the configured provider; it does not send the vendor, property, workspace, or original filename. Suggestions appear in an editable review form and are applied only after confirmation. Existing document metadata is never overwritten by AI suggestions. Public vendor upload links never call the AI provider automatically.

AI metadata can be inaccurate. CertDesk does not use extracted metadata to determine legal or insurance sufficiency, and the employee must verify the expiration date before it affects status and reminders. Provider processing, retention, and training terms are the operator's responsibility and must be reflected in the final privacy policy before launch.

## Stripe setup

1. Create two recurring monthly Prices in Stripe.
2. Add their IDs and your Stripe secret key to `.env`.
3. Run the app and register this webhook endpoint: `/billing/webhook/`.
4. Subscribe to `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`, `customer.subscription.deleted`, `invoice.paid`, and `invoice.payment_failed`.
5. Use Stripe CLI locally or the Dashboard test webhook endpoint for development.

The webhook activates the workspace after a completed Checkout and keeps subscription state synchronized from `checkout.session.completed`, `customer.subscription.created|updated|deleted`, `invoice.paid`, and `invoice.payment_failed` events. Stripe requires a successful 2xx response; invalid signatures are rejected with HTTP 400.

## Reminder job

Preview reminders without sending email:

```powershell
.\.venv\Scripts\python.exe manage.py send_expiration_reminders --dry-run
```

Send reminders for missing, expired, or soon-expiring documents:

```powershell
.\.venv\Scripts\python.exe manage.py send_expiration_reminders --days 30
```

The CSV importer expects these columns: `vendor`, `vendor_email`, `property` (optional), `document_type` (`coi`, `license`, `w9`, or `other`), and `due_date` (optional, `YYYY-MM-DD`). It creates missing vendors and properties, then adds document requests.

The reminder command uses the local console email backend by default and records one reminder per request and day to avoid duplicate sends. Schedule it daily with Windows Task Scheduler or your hosting platform's cron feature.

## Tests

Run the test suite from the project root:

```powershell
cd C:\CertDesk
.\.venv\Scripts\python.exe manage.py test
```

## Health check

`GET /health/` returns HTTP 200 with `{"status":"ok"}`. It is a lightweight liveness endpoint and does not run a database query; monitor database-backed workflows separately.

## Production deployment

The included `Dockerfile` supports container deployments, while `render.yaml` defines the Render web service and PostgreSQL database. The Blueprint mounts a 1 GB persistent disk at `/opt/render/project/src/media` and points `MEDIA_ROOT` there, so uploaded files survive redeploys while the service remains single-instance. Set `DEMO_MODE=False`, use the managed PostgreSQL URL, configure production email, and set Stripe keys. For Docker deployments outside Render, mount a durable volume at the configured `MEDIA_ROOT`; for a multi-instance deployment, replace local files with durable object storage.

For production, set `DEBUG=False`, `SESSION_COOKIE_SECURE=True`, `CSRF_COOKIE_SECURE=True`, `SECURE_SSL_REDIRECT=True`, and `SECURE_HSTS_SECONDS=31536000` (or another deliberate HSTS lifetime). The local `.env.example` disables HTTPS-related settings for plain-HTTP development, so do not carry those local values into production unchanged. Terminate TLS at the platform or reverse proxy and preserve the `X-Forwarded-Proto: https` header.

Before launch, also:

- replace the draft legal page with the operator's identity, terms, privacy policy, and support contact;
- configure and test the selected AI provider, including its model, multimodal request format, JSON mode, retention terms, and failure behavior;
- configure daily database backups and test restoration;
- add an email provider and verify deliverability;
- restrict `ALLOWED_HOSTS`, terminate HTTPS at the platform, and verify the production security settings with `manage.py check --deploy`;
- manually onboard three to five design partners and collect paid pilot commitments.

## Monetization notes

Published competitor anchors checked in November 2026:

- [COISoftware](https://coisoftware.com/): $49/month Starter, $149/month Plus
- [bcs](https://getbcs.com/pricing-and-plans): free up to 25 vendors, then $0.95/vendor/month

CertDesk deliberately targets the small-team segment at $29/$49 per month. Before expanding the feature set, validate willingness to pay with 15 interviewed property managers and secure at least three paid pilots.
