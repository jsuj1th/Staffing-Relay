# Hospital Leave Management System (LMS)

A working leave management system for 5 hospital locations. Employees request leave by texting a phone number. The system checks live Provider:MA staffing ratios and replies instantly. Managers get a web dashboard to oversee all locations and leaves.

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Architecture](#architecture)
3. [Business Rules](#business-rules)
4. [Data Model](#data-model)
5. [App Structure](#app-structure)
6. [Environment Variables](#environment-variables)
7. [Running Locally](#running-locally)
8. [Running with Docker](#running-with-docker)
9. [SMS Commands](#sms-commands)
10. [Dashboard URLs](#dashboard-urls)
11. [Testing](#testing)
12. [Deployment (AWS)](#deployment-aws)
13. [Future Roadmap](#future-roadmap)

---

## Quick Start

```bash
# 1. Create and activate virtualenv
python3 -m venv venv && source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy env file and configure
cp .env.example .env

# 4. Run migrations
DJANGO_SETTINGS_MODULE=lms.settings.local python manage.py migrate

# 5. Seed 5 hospitals + 47 employees + admin user
DJANGO_SETTINGS_MODULE=lms.settings.local python manage.py seed_data

# 6. Start the server
DJANGO_SETTINGS_MODULE=lms.settings.local python manage.py runserver

# Dashboard: http://localhost:8000/dashboard/
# Login:     admin / admin123
# SMS Test:  http://localhost:8000/sms-simulator/
```

---

## Architecture

```
Employee (any phone)
    │
    │  SMS: "LEAVE 2025-08-15"
    ▼
Telnyx (SMS gateway)
    │
    │  POST /webhooks/telnyx/  (Ed25519 signature verified)
    ▼
Django / Ratio Engine
    │  1. Look up employee by phone number
    │  2. Identify location + employee type
    │  3. Count active Providers and MAs (excl. existing approved leaves)
    │  4. Simulate ratio after leave for every requested day (worst-day-wins)
    │  5. Decide: APPROVED / EXTREME / REJECTED
    │  6. Create Leave record + SmsLog
    │  7. Send SMS reply via Telnyx
    ▼
PostgreSQL (AWS RDS in prod, SQLite locally)
    │
    ▼
Celery + Redis          Manager Dashboard
(async alerts)    ◄──── (Bootstrap 5, http://localhost:8000/dashboard/)
    │
    ▼
Manager SMS alert on EXTREME coverage
```

### Component Responsibilities

| Component | File(s) | Responsibility |
|---|---|---|
| **Webhook handler** | `apps/messaging/views.py` | Receives Telnyx events, routes commands, calls ratio engine |
| **SMS parser** | `apps/messaging/parser.py` | Extracts LEAVE / STATUS / CANCEL / HELP from raw text |
| **Ratio engine** | `apps/leaves/ratio.py` | Core business logic — counts active staff, evaluates leave |
| **SMS sender** | `apps/messaging/sms.py` | Thin Telnyx wrapper, gracefully no-ops without API key |
| **SMS simulator** | `apps/messaging/simulator.py` | Browser-based test form — no real phone needed |
| **Dashboard** | `apps/dashboard/views.py` | All manager-facing views |
| **Seed data** | `apps/accounts/management/commands/seed_data.py` | Creates hospitals + employees |

---

## Business Rules

### Employee Types

| Type | Location | Ratio Checked |
|---|---|---|
| **Provider** | Location-specific (one hospital) | Yes |
| **Medical Assistant** | Location-specific (one hospital) | Yes |
| **Front Desk** | Shared (multiple hospitals) | No — always approved |
| **Management** | Shared (multiple hospitals) | No — always approved |

### Provider : Medical Assistant Ratio

The ratio is calculated **per location** for **every calendar day** of the requested leave (worst-day-wins rule).

| Ratio (Providers:MAs) | State | Result |
|---|---|---|
| MAs ≥ Providers (e.g. 3:4, 3:3) | Ideal / Normal | **Approved** |
| Providers > MAs but ≤ 3:2 boundary | Extreme | **Approved** + manager alerted via SMS |
| Providers:MAs worse than 3:2 | Rejected | **Rejected** — employee told to contact manager |

**Threshold check (integer arithmetic — no float drift):**
```python
if p_after * 2 > ma_after * 3:   # worse than 3:2 → REJECTED
    ...
elif p_after > ma_after:          # between 1:1 and 3:2 → EXTREME
    ...
else:                             # p_after <= ma_after → APPROVED
    ...
```

### What employees see vs. what managers see

| Audience | Leave outcome | Ratio numbers |
|---|---|---|
| Employee (SMS) | "Approved" / "Please coordinate with team" / "Cannot be approved" | **Never shown** |
| Manager (Dashboard) | Full status + internal_note | Shown as `3P:2MA → 2P:2MA` |

---

## Data Model

```
Location
├── id, name, address, city, state, phone
└── direct_employees (PROVIDER + MA)

Employee
├── id, name, phone (unique, E.164), employee_type, is_active
├── location → FK Location (required for PROVIDER/MA, null for FRONT_DESK/MANAGEMENT)
└── employee_locations → M2M via EmployeeLocation (for shared staff)

EmployeeLocation         ← shared staff assignments
├── employee → FK Employee
├── location → FK Location
└── is_primary

Leave
├── id, employee, start_date, end_date, reason
├── status: PENDING | APPROVED | EXTREME | REJECTED | CANCELLED
├── ratio_before: JSON {"providers": 3, "mas": 4}   ← internal, manager-only
├── ratio_after:  JSON {"providers": 2, "mas": 4}   ← internal, manager-only
├── internal_note: text (ratio summary for audit)
└── approved_by → FK User (null = auto-decided via SMS)

SmsLog                   ← every inbound + outbound message
├── from_phone, employee (nullable)
├── inbound_msg, outbound_msg
└── leave (nullable FK)

LoyaltyPoint             ← stub, not yet active
├── employee, points, reason
```

---

## App Structure

```
lms/                          Django project root
├── manage.py
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
│
├── lms/                      Project config package
│   ├── settings/
│   │   ├── base.py           Shared settings (DB, Telnyx, Celery, templates)
│   │   ├── local.py          DEBUG=True, SQLite, ALLOWED_HOSTS=*
│   │   └── production.py     S3 static files, HTTPS, CloudWatch logging
│   ├── urls.py               Root URL config
│   └── celery.py             Celery app init
│
├── apps/
│   ├── accounts/             Employee model, seed command
│   ├── locations/            Location + EmployeeLocation models
│   ├── leaves/               Leave model + ratio engine (ratio.py)
│   ├── messaging/            Telnyx webhook, SMS parser, simulator, SmsLog
│   ├── dashboard/            Manager UI views, URLs, health check
│   └── loyalty/              Stub — LoyaltyPoint model only
│
├── templates/
│   ├── base.html             Sidebar layout with Bootstrap 5
│   ├── dashboard/            overview, employees, employee_form, leaves,
│   │                         sms_logs, location_detail
│   ├── registration/         login.html
│   └── simulator/            sms_simulator.html
│
└── static/                   CSS + JS (served via S3 in production)
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in:

```env
# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Database
# Local dev (SQLite):
DATABASE_URL=sqlite:///db.sqlite3
# Production (PostgreSQL):
# DATABASE_URL=postgres://user:pass@rds-endpoint:5432/lms_db

# Telnyx SMS
TELNYX_API_KEY=           # From portal.telnyx.com → API Keys
TELNYX_PUBLIC_KEY=        # From portal.telnyx.com → Keys & Credentials → Public Key
TELNYX_PHONE_NUMBER=+1... # Your purchased Telnyx number (E.164)

# Celery / Redis
REDIS_URL=redis://localhost:6379/0

# AWS (production only)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=us-east-1
```

> **No Telnyx keys?** The system still works fully — SMS sends are skipped with a warning log. Use the SMS Simulator at `/sms-simulator/` to test the full flow in the browser.

---

## Running Locally

### Without Docker (SQLite, fastest)

```bash
source venv/bin/activate
export DJANGO_SETTINGS_MODULE=lms.settings.local

python manage.py migrate
python manage.py seed_data          # idempotent — safe to re-run
python manage.py runserver
```

### Reset and re-seed from scratch

```bash
python manage.py seed_data --reset
```

### Run Celery worker (optional — needed for async manager alerts)

```bash
celery -A lms worker --loglevel=info
```

### Test Telnyx webhook locally with ngrok

```bash
ngrok http 8000
# Copy the https URL, e.g. https://abc123.ngrok.io
# In Telnyx Mission Control → Messaging → your profile → Webhook URL:
#   https://abc123.ngrok.io/webhooks/telnyx/
```

---

## Running with Docker

Full stack (web + PostgreSQL + Redis + Celery):

```bash
docker-compose up --build
```

This runs migrations and seeds data automatically on first start.

| Service | Port |
|---|---|
| Django web | `http://localhost:8000` |
| PostgreSQL | `localhost:5432` |
| Redis | `localhost:6379` |

---

## SMS Commands

Employees text the Telnyx number. All commands are case-insensitive.

| Command | Format | Description |
|---|---|---|
| Request leave | `LEAVE YYYY-MM-DD` | Single day leave |
| Request leave | `LEAVE YYYY-MM-DD YYYY-MM-DD` | Date range leave |
| Request leave | `LEAVE YYYY-MM-DD YYYY-MM-DD reason` | With optional reason |
| Check status | `STATUS` | Lists upcoming approved/pending leaves (dates only) |
| Cancel leave | `CANCEL` | Cancels the one upcoming leave, or lists dates if multiple |
| Cancel leave | `CANCEL YYYY-MM-DD` | Cancels leave starting on that date |
| Get help | `HELP` | Returns this command list |

**Edge cases handled:**
- Past dates → rejected with explanation
- Overlapping existing leaves → rejected with dates of conflict
- Unknown phone number → "not registered, contact HR"
- Unrecognized message → returns HELP text

---

## Dashboard URLs

All require login (`admin / admin123` for the seeded superuser).

| URL | Page |
|---|---|
| `/dashboard/` | Overview — 5 location cards with ratio badges |
| `/dashboard/employees/` | Employee list (filterable by type + location) |
| `/dashboard/employees/new/` | Add employee |
| `/dashboard/employees/<id>/edit/` | Edit employee |
| `/dashboard/leaves/` | Leave queue — approve/reject with SMS notification |
| `/dashboard/sms/` | SMS audit log |
| `/dashboard/locations/<id>/` | Location detail — roster + ratio + leave history |
| `/sms-simulator/` | **Prototype tool** — test any employee's SMS flow in browser |
| `/admin/` | Django admin — full data browser |
| `/health/` | Health check endpoint (returns `{"status": "ok"}`) |

---

## Testing

```bash
# Run all tests
DJANGO_SETTINGS_MODULE=lms.settings.local python manage.py test apps

# Run specific test modules
python manage.py test apps.leaves.tests      # Ratio engine (21 tests)
python manage.py test apps.messaging.tests   # SMS parser + webhook (14 tests)
```

**Test coverage includes:**
- Ratio engine: zero-MA edge case, exact 3:2 integer boundary, multi-day worst-day-wins
- SMS parser: single day, date range, reason extraction, CANCEL with/without date
- Webhook handler: unknown number, past date, overlapping leaves, non-message events
- Employee type routing: FRONT_DESK/MANAGEMENT auto-approved (ratio skipped)

---

## Deployment (AWS)

### Required AWS resources

| Resource | Service | Notes |
|---|---|---|
| App containers | ECS Fargate | 2 tasks: `web` (gunicorn) + `celery` (worker) |
| Container registry | ECR | One repo: `hospital-lms` |
| Database | RDS PostgreSQL 15 | `t3.micro` to start |
| Cache / broker | ElastiCache Redis | `t3.micro`, used by Celery |
| Load balancer | ALB | Routes HTTPS → port 8000 |
| SSL certificate | ACM | Attach to ALB listener |
| Static files | S3 + CloudFront | `django-storages` writes to S3 on `collectstatic` |
| Secrets | Secrets Manager | All `.env` values |
| Logs | CloudWatch | ECS streams stdout → log groups |

### CI/CD pipeline

`.github/workflows/deploy.yml` runs on every push to `main`:

```
Push to main
  └── Run tests (against PostgreSQL service container)
      └── Build Docker image
          └── Push to ECR
              └── Update ECS task definition
                  └── Deploy to ECS (waits for stability)
```

**Secrets required in GitHub repository settings:**
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

### Production settings

`lms/settings/production.py` enables:
- `SECURE_SSL_REDIRECT = True`
- `SESSION_COOKIE_SECURE = True`
- Static files → S3 via `django-storages`
- Structured logging to stdout (captured by CloudWatch)

### First production deploy checklist

- [ ] RDS instance created, `DATABASE_URL` added to Secrets Manager
- [ ] ElastiCache Redis created, `REDIS_URL` added to Secrets Manager
- [ ] S3 bucket created for static files, `collectstatic` runs in Dockerfile
- [ ] ACM certificate issued and attached to ALB
- [ ] Telnyx webhook URL updated to `https://your-domain.com/webhooks/telnyx/`
- [ ] `python manage.py migrate` run as a one-off ECS task before first deploy
- [ ] `python manage.py seed_data` run once to bootstrap locations

---

## Future Roadmap

### Loyalty Rewards (model stub exists in `apps/loyalty/`)
- Award points for: leave cancelled on short notice, no leave taken in a period, positive ratio contribution
- Redeem for: priority leave approval, recognition badges
- Dashboard view: employee leaderboard per location

### Analytics Dashboard
- Ratio trend chart per location (30/60/90 day)
- Leave frequency heatmap by day of week
- Provider vs MA leave correlation analysis
- Export to CSV

### Multi-language SMS
- Detect employee language preference from profile
- Reply in the same language the message was sent in

### Leave Calendar Integration
- `.ics` export for approved leaves
- Two-way Google/Outlook calendar sync

---

## Seeded Hospitals

| # | Hospital | City | State |
|---|---|---|---|
| 1 | St. Mary's Medical Center | Chicago | IL |
| 2 | Riverside Health Center | Austin | TX |
| 3 | North Valley Hospital | Denver | CO |
| 4 | County General Hospital | Phoenix | AZ |
| 5 | Eastside Medical Clinic | Atlanta | GA |

Each location has: 4 Providers, 4 Medical Assistants, shared Front Desk and Management staff.

Sample employee phone numbers follow the pattern `+1XXX55501YY` (Providers) and `+1XXX55502YY` (MAs) where `XXX` is the location area code.
