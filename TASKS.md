# Relay LMS — Task Tracker

> **Project:** Relay (Hospital Leave Management System)
> **Stack:** Django 5.2 · Telnyx SMS · Celery · AWS ECS Fargate
> **Last updated:** 2026-07-05

---

## In Progress

*Current sprint tasks — started 2026-07-05*

- [ ] Apply Relay prototype design system to all Django templates (`base.html`, overview, employees, leaves, SMS simulator, SMS logs, location detail, login) — warm earth tones (`#EAE3D7` bg, `#8A3A2E` brand, Spectral / IBM Plex fonts)
- [ ] Add NLP-based natural language parsing to SMS parser (`python-dateparser` integration, intent detection for ambiguous inputs)
- [ ] Add Python logging statements throughout all app modules (`ratio.py`, `views.py`, `sms.py`, `simulator.py`, dashboard views, `parser.py`)

---

## Completed

*Recently shipped*

- [x] Core ratio engine with 3:2 Provider:MA check (`evaluate_leave` function)
- [x] Telnyx SMS webhook with Ed25519 signature verification
- [x] Django admin registration for all models
- [x] Seed data command for 5 hospitals + 47 employees
- [x] Basic manager dashboard (overview, employees, leaves, SMS logs, location detail)
- [x] SMS command parser (`LEAVE`, `STATUS`, `CANCEL`, `HELP`)
- [x] SMS simulator for browser testing
- [x] Docker + docker-compose local dev stack
- [x] GitHub Actions CI/CD pipeline to AWS ECS Fargate
- [x] AWS production infrastructure (ECS, RDS, ElastiCache, S3, CloudFront)
- [x] 35 unit tests (ratio engine + SMS parser)

---

## Backlog

*Future work — not yet scheduled*

- [ ] **Employee Tracker view:** YTD leave stats (total approved, avg days/employee, out today) — matches Relay prototype "Tracker" tab
- [ ] **Location presence modal:** click location card → see who's on shift today (matches prototype)
- [ ] **Loyalty points system:** activate the stubbed `LoyaltyPoint` model (points per leave taken, per year of service)
- [ ] **Manager leave override:** web UI button to override auto-SMS decisions on dashboard
- [ ] **Push notifications:** browser push when new EXTREME/PENDING leave arrives
- [ ] **NLP response improvement:** detect ambiguous dates and ask clarifying follow-up via SMS
- [ ] **Multi-language SMS support:** Spanish translation of leave responses
- [ ] **Leave calendar view:** month-grid showing who is out on each day per location
- [ ] **Shift coverage report:** PDF export of coverage ratios by date range
- [ ] **Employee self-service portal:** web login for employees to view/cancel their own leaves
- [ ] **Celery async SMS alerts:** currently synchronous, move to Celery tasks for reliability
- [ ] **Rate limiting:** prevent SMS flood from single phone number
