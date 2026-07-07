# Shift Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let managers assign employees to shifts (date + start/end time), and make the leave ratio engine count only employees who are actually scheduled that day, instead of every active employee.

**Architecture:** New Django app `apps.shifts` with a single `Shift` model (employee, date, start_time, end_time). `apps/leaves/ratio.py::get_active_counts` is changed to intersect its existing active/not-on-leave employee query with "has a Shift row in the date range" — no shift on a date means that employee is not counted as on duty for that date. Dashboard gets a day-view page (pick location + date, see who's scheduled, add/edit/delete shifts) with a "repeat for next N weeks" bulk-create option on the add form.

**Tech Stack:** Django 5.2.15, `django.test.TestCase` (no factory libraries), function-based views, no Django Forms (manual `request.POST` parsing per existing convention), server-rendered templates with inline styles (Relay design system tokens), SQLite for tests/dev.

## Global Constraints

- Follow existing app conventions exactly: function-based views, `@login_required`, manual POST parsing + `messages.error`/`messages.success`, `get_object_or_404`, no new dependencies (no Forms library, no DRF serializers for this feature — it's server-rendered HTML only).
- No overlap/conflict validation between shifts (spec explicitly excludes this).
- No recurring-template model — "repeat for N weeks" is a bulk-create loop at save time producing independent `Shift` rows.
- `Shift` has no `location` field — location is always `employee.location`.
- Relay design tokens (from existing templates): panel bg `#F1EADD`/`#FBF9F4`, border `#E4DACB`/`#D6CBBA`, text `#2B2521`, muted `#9A8D7E`/`#8A8073`, brand `#8A3A2E`, fonts `'Spectral',serif` (names/headers), `'IBM Plex Mono',monospace` (labels/badges, uppercase, letter-spacing 0.08em), `'IBM Plex Sans',sans-serif` (body). Buttons: `.relay-btn`, `.relay-btn-primary`, `.relay-btn-approve`.
- Every task ends with `python manage.py test` passing for the whole suite, not just the new test file — the ratio engine change affects `apps/leaves/tests.py` and that must be verified green before moving on.

---

### Task 1: Create the `shifts` app and `Shift` model

**Files:**
- Create: `apps/shifts/__init__.py`
- Create: `apps/shifts/apps.py`
- Create: `apps/shifts/models.py`
- Create: `apps/shifts/admin.py`
- Create: `apps/shifts/migrations/__init__.py`
- Create: `apps/shifts/tests.py`
- Modify: `lms/settings/base.py:13-27` (INSTALLED_APPS)

**Interfaces:**
- Produces: `apps.shifts.models.Shift` with fields `employee` (FK to `accounts.Employee`, `related_name="shifts"`), `date` (DateField), `start_time` (TimeField), `end_time` (TimeField), `created_by` (FK to `auth.User`, nullable), `created_at` (auto). `Shift.__str__()` returns `"{employee.name} — {date} {start_time}-{end_time}"`. Later tasks (2, 3) import this as `from apps.shifts.models import Shift`.

Django requires an app to be listed in `INSTALLED_APPS` before any of its models can be defined (model class creation fails at import time otherwise), so this task registers the app first, then adds a failing test that imports the not-yet-written model, then implements it.

- [ ] **Step 1: Create empty app package and register it**

Create `apps/shifts/__init__.py` (empty file).

Create `apps/shifts/apps.py`:
```python
from django.apps import AppConfig


class ShiftsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.shifts"
```

Create `apps/shifts/migrations/__init__.py` (empty file).

Edit `lms/settings/base.py` — in the `INSTALLED_APPS` list (currently lines 13-27), add `"apps.shifts"` after `"apps.loyalty"`:
```python
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "apps.accounts",
    "apps.locations",
    "apps.leaves",
    "apps.messaging",
    "apps.dashboard",
    "apps.loyalty",
    "apps.shifts",
]
```

- [ ] **Step 2: Write the failing test**

Create `apps/shifts/tests.py`:
```python
from datetime import date, time
from django.test import TestCase

from apps.accounts.models import Employee
from apps.locations.models import Location
from apps.shifts.models import Shift


class ShiftModelTests(TestCase):
    def setUp(self):
        self.location = Location.objects.create(
            name="Test Hospital", address="1 Main St", city="Testville", state="TX"
        )
        self.employee = Employee.objects.create(
            name="Dr. Test",
            phone="+15550001234",
            employee_type=Employee.Type.PROVIDER,
            location=self.location,
        )

    def test_create_shift(self):
        shift = Shift.objects.create(
            employee=self.employee,
            date=date(2026, 8, 3),
            start_time=time(9, 0),
            end_time=time(17, 0),
        )
        self.assertEqual(shift.employee, self.employee)
        self.assertIn(self.employee.name, str(shift))

    def test_multiple_shifts_same_day_allowed(self):
        """No overlap validation — split shifts are allowed."""
        Shift.objects.create(
            employee=self.employee, date=date(2026, 8, 3),
            start_time=time(7, 0), end_time=time(11, 0),
        )
        Shift.objects.create(
            employee=self.employee, date=date(2026, 8, 3),
            start_time=time(12, 0), end_time=time(16, 0),
        )
        self.assertEqual(
            Shift.objects.filter(employee=self.employee, date=date(2026, 8, 3)).count(),
            2,
        )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python manage.py test apps.shifts -v 2`
Expected: FAIL/ERROR — `ImportError: cannot import name 'Shift' from 'apps.shifts.models'` (module `apps/shifts/models.py` doesn't exist yet).

- [ ] **Step 4: Implement the model**

Create `apps/shifts/models.py`:
```python
from django.conf import settings
from django.db import models


class Shift(models.Model):
    employee = models.ForeignKey(
        "accounts.Employee",
        on_delete=models.CASCADE,
        related_name="shifts",
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "start_time"]

    def __str__(self):
        return f"{self.employee.name} — {self.date} {self.start_time}-{self.end_time}"
```

- [ ] **Step 5: Generate and apply the migration**

Run: `python manage.py makemigrations shifts`
Expected output: `Migrations for 'shifts': apps/shifts/migrations/0001_initial.py - Create model Shift`

Run: `python manage.py migrate shifts`
Expected output: `Applying shifts.0001_initial... OK`

- [ ] **Step 6: Run test to verify it passes**

Run: `python manage.py test apps.shifts -v 2`
Expected: `OK` (2 tests passed).

- [ ] **Step 7: Register admin**

Create `apps/shifts/admin.py`:
```python
from django.contrib import admin
from .models import Shift


@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ["employee", "date", "start_time", "end_time", "created_by"]
    list_filter = ["date", "employee__location"]
    search_fields = ["employee__name"]
    date_hierarchy = "date"
```

- [ ] **Step 8: Commit**

```bash
git add apps/shifts lms/settings/base.py
git commit -m "feat: add Shift model and shifts app"
```

---

### Task 2: Make the ratio engine count only scheduled employees

**Files:**
- Modify: `apps/leaves/ratio.py:17-51` (`get_active_counts`)
- Modify: `apps/leaves/tests.py` (setUp fixture + new tests)

**Interfaces:**
- Consumes: `apps.shifts.models.Shift` (Task 1) — fields `employee`, `date`.
- Produces: `get_active_counts(location_id, start_date, end_date, exclude_employee_id=None)` keeps its existing signature and `(provider_count, ma_count)` return type; callers in `apps/dashboard/views.py` and `apps/locations/models.py` (`Location.get_ratio_today`) are unaffected by signature — only by behavior.

This task changes core business logic, which breaks every existing test in `apps/leaves/tests.py` that currently assumes "active = on duty" (they created employees with no shifts, so after this change every count would drop to zero). The fix is applied in one pass: add new tests proving the new behavior, watch them fail, implement the change, then update `setUp()` to give every test employee a shift across the full date range the test file uses (spanning `today - 1` to `today + 40`, which covers every relative date used anywhere in the file: `today`, `tomorrow`, `today+2`, `today+10`, `today+30`), then confirm the whole suite passes again.

- [ ] **Step 1: Write failing tests for shift-based counting**

Add to `apps/leaves/tests.py`, after the imports (add `from apps.shifts.models import Shift` to the existing import block) and as new methods on `RatioEngineTests` (after `test_active_counts_exclude_employee_id`):

```python
    def test_no_shifts_means_nobody_counted(self):
        """A date with zero Shift rows anywhere → nobody is on duty."""
        far_future = self.today + timedelta(days=200)
        p, ma = get_active_counts(self.location.id, far_future, far_future)
        self.assertEqual(p, 0)
        self.assertEqual(ma, 0)

    def test_only_scheduled_employees_counted(self):
        """Employees without a shift on the date don't count, even if is_active."""
        target_date = self.today + timedelta(days=201)
        Shift.objects.create(
            employee=self.providers[0], date=target_date,
            start_time="09:00", end_time="17:00",
        )
        Shift.objects.create(
            employee=self.mas[0], date=target_date,
            start_time="09:00", end_time="17:00",
        )
        p, ma = get_active_counts(self.location.id, target_date, target_date)
        self.assertEqual(p, 1)
        self.assertEqual(ma, 1)
```

Update the top of `apps/leaves/tests.py` — change:
```python
from apps.leaves.ratio import get_active_counts, evaluate_leave
```
to:
```python
from apps.leaves.ratio import get_active_counts, evaluate_leave
from apps.shifts.models import Shift
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `python manage.py test apps.leaves -v 2`
Expected: `test_no_shifts_means_nobody_counted` and `test_only_scheduled_employees_counted` FAIL (current code returns `p=3, ma=4` for `test_no_shifts_means_nobody_counted` since it ignores shifts entirely; `test_only_scheduled_employees_counted` gets `p=3, ma=4` instead of `p=1, ma=1`). All other tests in the file still PASS at this point — this confirms the new tests correctly exercise unimplemented behavior.

- [ ] **Step 3: Implement the ratio engine change**

In `apps/leaves/ratio.py`, replace the body of `get_active_counts` (lines 17-51):

```python
def get_active_counts(location_id: int, start_date: date, end_date: date, exclude_employee_id: int = None):
    """
    Returns (provider_count, ma_count) of employees who are is_active, NOT on
    APPROVED/EXTREME leave for any day in the given range, AND have at least
    one Shift on a day in the given range at the given location.
    """
    from apps.leaves.models import Leave
    from apps.accounts.models import Employee
    from apps.shifts.models import Shift

    # Employees at this location on leave during the date range
    on_leave_qs = Leave.objects.filter(
        employee__location_id=location_id,
        status__in=[Leave.Status.APPROVED, Leave.Status.EXTREME],
        start_date__lte=end_date,
        end_date__gte=start_date,
    )
    if exclude_employee_id is not None:
        on_leave_qs = on_leave_qs.exclude(employee_id=exclude_employee_id)

    on_leave_ids = set(on_leave_qs.values_list("employee_id", flat=True))

    scheduled_ids = set(
        Shift.objects.filter(
            employee__location_id=location_id,
            date__gte=start_date,
            date__lte=end_date,
        ).values_list("employee_id", flat=True)
    )

    base_qs = Employee.objects.filter(
        location_id=location_id, is_active=True, id__in=scheduled_ids
    )

    providers = base_qs.filter(
        employee_type=Employee.Type.PROVIDER
    ).exclude(id__in=on_leave_ids).count()

    mas = base_qs.filter(
        employee_type=Employee.Type.MEDICAL_ASSISTANT
    ).exclude(id__in=on_leave_ids).count()

    logger.debug(
        "get_active_counts: location=%s start=%s end=%s providers=%d mas=%d",
        location_id, start_date, end_date, providers, mas,
    )
    return providers, mas
```

- [ ] **Step 4: Run tests to verify the new tests pass (others will now fail — expected)**

Run: `python manage.py test apps.leaves.tests.RatioEngineTests.test_no_shifts_means_nobody_counted apps.leaves.tests.RatioEngineTests.test_only_scheduled_employees_counted -v 2`
Expected: `OK` (2 tests passed).

- [ ] **Step 5: Update the test fixture so pre-existing tests reflect scheduled employees**

In `apps/leaves/tests.py`, in `RatioEngineTests.setUp`, immediately after the `self.tomorrow = ...` line, add:

```python
        # Give every employee a shift across every relative date used anywhere
        # in this file (today, tomorrow, today+2, today+10, today+30, etc.)
        # so pre-existing tests keep exercising "on duty" employees under the
        # new shift-based counting rule.
        for offset in range(-1, 40):
            shift_date = self.today + timedelta(days=offset)
            for emp in self.providers + self.mas:
                Shift.objects.create(
                    employee=emp, date=shift_date,
                    start_time="09:00", end_time="17:00",
                )
```

- [ ] **Step 6: Run the full leaves test suite to verify everything passes**

Run: `python manage.py test apps.leaves -v 2`
Expected: `OK` — all tests pass, including the two new ones (their target dates — `today+200`, `today+201` — fall outside the `setUp` shift range of `today-1` to `today+39`, so they're unaffected by the fixture change).

- [ ] **Step 7: Run the whole project test suite**

Run: `python manage.py test -v 2`
Expected: `OK` — no regressions in `apps.accounts`, `apps.messaging`, or `apps.shifts`.

- [ ] **Step 8: Commit**

```bash
git add apps/leaves/ratio.py apps/leaves/tests.py
git commit -m "feat: ratio engine counts only employees with a shift that day"
```

---

### Task 3: Dashboard views and URLs for shift assignment

**Files:**
- Modify: `apps/dashboard/views.py` (add shift views)
- Modify: `apps/dashboard/urls.py` (add shift routes)

**Interfaces:**
- Consumes: `apps.shifts.models.Shift` (Task 1); `apps.accounts.models.Employee`, `apps.locations.models.Location` (existing).
- Produces: views `shift_day(request)`, `shift_create(request)`, `shift_edit(request, pk)`, `shift_delete(request, pk)`; URL names `dashboard:shifts`, `dashboard:shift_create`, `dashboard:shift_edit`, `dashboard:shift_delete`. Task 4's templates render against the context these views build (documented in each step below).

No new automated tests in this task — the codebase has no existing tests for `apps/dashboard/views.py` (it's all manually/browser-verified per existing convention: `leave_list`, `employee_create`, etc. have no test coverage either). Verification here is manual: run the dev server and exercise each view after Task 4 adds templates. This task and Task 4 are verified together at the end of Task 4.

- [ ] **Step 1: Add the day-view (list) route and view**

In `apps/dashboard/urls.py`, add after the `leaves/...` routes (after line 14, before `path("sms/", ...)`):
```python
    path("shifts/", views.shift_day, name="shifts"),
    path("shifts/new/", views.shift_create, name="shift_create"),
    path("shifts/<int:pk>/edit/", views.shift_edit, name="shift_edit"),
    path("shifts/<int:pk>/delete/", views.shift_delete, name="shift_delete"),
```

In `apps/dashboard/views.py`, add the import (with the other model imports near the top):
```python
from apps.shifts.models import Shift
```

Add the view (after `location_detail`, at the end of the file):
```python
@login_required
def shift_day(request):
    today = timezone.localdate()
    location_id = request.GET.get("location", "")
    date_str = request.GET.get("date", "")
    selected_date = date_str and date.fromisoformat(date_str) or today

    locations = Location.objects.all()
    selected_location = None
    employees = Employee.objects.none()
    shifts_by_employee = {}

    if location_id:
        selected_location = get_object_or_404(Location, pk=location_id)
        employees = Employee.objects.filter(
            location=selected_location,
            employee_type__in=[Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT],
            is_active=True,
        ).order_by("name")
        day_shifts = Shift.objects.filter(
            employee__in=employees, date=selected_date
        ).select_related("employee")
        for shift in day_shifts:
            shifts_by_employee.setdefault(shift.employee_id, []).append(shift)

    rows = [
        {"employee": emp, "shifts": shifts_by_employee.get(emp.id, [])}
        for emp in employees
    ]

    return render(request, "dashboard/shifts.html", {
        "locations": locations,
        "selected_location": selected_location,
        "selected_date": selected_date,
        "rows": rows,
        "today": today,
    })
```

Add the required import at the top of `apps/dashboard/views.py` — change:
```python
from django.utils import timezone
```
to:
```python
from datetime import date
from django.utils import timezone
```

- [ ] **Step 2: Add the create view with "repeat for N weeks"**

Add to `apps/dashboard/views.py`, after `shift_day`:
```python
@login_required
def shift_create(request):
    locations = Location.objects.all()
    preselect_location_id = request.GET.get("location", "")
    preselect_date = request.GET.get("date", "")

    if request.method == "POST":
        employee_id = request.POST.get("employee_id")
        shift_date_str = request.POST.get("date", "")
        start_time = request.POST.get("start_time", "")
        end_time = request.POST.get("end_time", "")
        repeat_weeks = int(request.POST.get("repeat_weeks") or 0)

        if not (employee_id and shift_date_str and start_time and end_time):
            messages.error(request, "Employee, date, start time, and end time are required.")
            return render(request, "dashboard/shift_form.html", {
                "locations": locations, "action": "Add",
                "preselect_location_id": preselect_location_id,
                "preselect_date": preselect_date,
            })

        employee = get_object_or_404(Employee, pk=employee_id)
        shift_date = date.fromisoformat(shift_date_str)

        Shift.objects.create(
            employee=employee, date=shift_date,
            start_time=start_time, end_time=end_time,
            created_by=request.user,
        )
        for week in range(1, repeat_weeks + 1):
            Shift.objects.create(
                employee=employee, date=shift_date + timedelta(weeks=week),
                start_time=start_time, end_time=end_time,
                created_by=request.user,
            )

        logger.info("Shift created: employee=%s date=%s repeat_weeks=%d", employee.name, shift_date, repeat_weeks)
        messages.success(request, f"Shift added for {employee.name}" + (f" (repeated {repeat_weeks} weeks)" if repeat_weeks else "") + ".")
        return redirect(f"/dashboard/shifts/?location={employee.location_id}&date={shift_date_str}")

    employees = Employee.objects.filter(
        employee_type__in=[Employee.Type.PROVIDER, Employee.Type.MEDICAL_ASSISTANT],
        is_active=True,
    ).select_related("location").order_by("name")
    return render(request, "dashboard/shift_form.html", {
        "locations": locations, "employees": employees, "action": "Add",
        "preselect_location_id": preselect_location_id,
        "preselect_date": preselect_date,
    })
```

Add `timedelta` to the existing `datetime` import — change:
```python
from datetime import date
```
to:
```python
from datetime import date, timedelta
```

- [ ] **Step 3: Add edit and delete views**

Add to `apps/dashboard/views.py`, after `shift_create`:
```python
@login_required
def shift_edit(request, pk):
    shift = get_object_or_404(Shift, pk=pk)

    if request.method == "POST":
        shift.date = date.fromisoformat(request.POST.get("date", str(shift.date)))
        shift.start_time = request.POST.get("start_time", shift.start_time)
        shift.end_time = request.POST.get("end_time", shift.end_time)
        shift.save()
        logger.info("Shift updated: id=%d employee=%s", shift.id, shift.employee.name)
        messages.success(request, "Shift updated.")
        return redirect(f"/dashboard/shifts/?location={shift.employee.location_id}&date={shift.date}")

    return render(request, "dashboard/shift_form.html", {
        "shift": shift, "action": "Edit",
        "locations": Location.objects.all(),
    })


@login_required
def shift_delete(request, pk):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    shift = get_object_or_404(Shift, pk=pk)
    location_id = shift.employee.location_id
    shift_date = shift.date
    employee_name = shift.employee.name
    shift.delete()
    logger.info("Shift deleted: employee=%s date=%s", employee_name, shift_date)
    messages.success(request, f"Shift removed for {employee_name}.")
    return redirect(f"/dashboard/shifts/?location={location_id}&date={shift_date}")
```

Also simplify the success redirect at the end of `shift_create` (Step 2) to the same plain form — replace its `return redirect(...)` line with:
```python
    return redirect(f"/dashboard/shifts/?location={employee.location_id}&date={shift_date_str}")
```

- [ ] **Step 4: Verify the app boots with the new routes**

Run: `python manage.py check`
Expected: `System check identified no issues (0 silenced).`

Run: `python manage.py test`
Expected: `OK` (no test files reference these views yet, so this just confirms nothing broke at import time).

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py
git commit -m "feat: add dashboard views and routes for shift assignment"
```

---

### Task 4: Shift templates and navigation

**Files:**
- Create: `templates/dashboard/shifts.html`
- Create: `templates/dashboard/shift_form.html`
- Modify: `templates/base.html:582-594` (sidebar nav)

**Interfaces:**
- Consumes context from Task 3's views: `shift_day` provides `locations`, `selected_location`, `selected_date`, `rows` (list of `{"employee": Employee, "shifts": [Shift, ...]}`), `today`. `shift_create`/`shift_edit` provide `locations`, `employees` (create only), `action`, `preselect_location_id`, `preselect_date` (create only), `shift` (edit only).

- [ ] **Step 1: Add the day-view template**

Create `templates/dashboard/shifts.html`:
```html
{% extends "base.html" %}
{% block title %}Shifts — Relay{% endblock %}

{% block content %}
<div class="mb-4">
  <h2 class="page-title">Shifts</h2>
  <div class="section-label" style="margin-top:4px">who's scheduled, by location and date</div>
</div>

<div style="background:#F1EADD;border:1px solid #E4DACB;padding:14px 18px;margin-bottom:20px;">
  <form method="get" class="row g-2 align-items-end">
    <div class="col-auto">
      <label style="font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#9A8D7E;display:block;margin-bottom:6px;">Location</label>
      <select name="location" style="font-family:'IBM Plex Sans',sans-serif;font-size:14px;background:#FBF9F4;border:1px solid #D6CBBA;border-radius:0;color:#2B2521;padding:6px 10px;">
        <option value="">Select location...</option>
        {% for loc in locations %}
          <option value="{{ loc.id }}" {% if selected_location.id == loc.id %}selected{% endif %}>{{ loc.name }}</option>
        {% endfor %}
      </select>
    </div>
    <div class="col-auto">
      <label style="font-family:'IBM Plex Mono',monospace;font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:#9A8D7E;display:block;margin-bottom:6px;">Date</label>
      <input type="date" name="date" value="{{ selected_date|date:'Y-m-d' }}"
             style="font-family:'IBM Plex Mono',monospace;font-size:14px;background:#FBF9F4;border:1px solid #D6CBBA;border-radius:0;color:#2B2521;padding:6px 10px;">
    </div>
    <div class="col-auto d-flex gap-2">
      <button type="submit" class="relay-btn">View</button>
      {% if selected_location %}
      <a class="relay-btn relay-btn-primary" href="{% url 'dashboard:shift_create' %}?location={{ selected_location.id }}&date={{ selected_date|date:'Y-m-d' }}">+ Add Shift</a>
      {% endif %}
    </div>
  </form>
</div>

{% if not selected_location %}
  <div style="background:#F1EADD;border:1px solid #E4DACB;padding:40px;text-align:center;font-family:'IBM Plex Sans',sans-serif;font-size:15px;color:#9A8D7E;">
    Select a location and date to view shifts.
  </div>
{% else %}
  <div class="row g-0" style="padding:0 18px 8px 18px;">
    <div class="col-md-4" style="font-family:'IBM Plex Mono',monospace;font-size:13px;color:#B0A596;letter-spacing:0.06em;text-transform:uppercase;">Employee</div>
    <div class="col-md-6" style="font-family:'IBM Plex Mono',monospace;font-size:13px;color:#B0A596;letter-spacing:0.06em;text-transform:uppercase;">Shift(s)</div>
    <div class="col-md-2" style="font-family:'IBM Plex Mono',monospace;font-size:13px;color:#B0A596;letter-spacing:0.06em;text-transform:uppercase;">Actions</div>
  </div>

  {% for row in rows %}
  <div class="row g-0 align-items-center" style="background:#F1EADD;border-left:4px solid {% if row.shifts %}#5F7A52{% else %}#9A8D7E{% endif %};margin-bottom:8px;padding:14px 18px;">
    <div class="col-md-4">
      <div style="font-family:'Spectral',serif;font-size:20px;font-weight:600;color:#2B2521;line-height:1.2;">{{ row.employee.name }}</div>
      <div style="font-family:'IBM Plex Sans',sans-serif;font-size:14px;color:#8A8073;">{{ row.employee.get_employee_type_display }}</div>
    </div>
    <div class="col-md-6" style="font-family:'IBM Plex Mono',monospace;font-size:15px;color:#2B2521;">
      {% for shift in row.shifts %}
        {{ shift.start_time|time:"H:i" }}–{{ shift.end_time|time:"H:i" }}
        <a href="{% url 'dashboard:shift_edit' shift.pk %}" class="relay-btn" style="font-size:12px;padding:3px 8px;">Edit</a>
        <form method="post" action="{% url 'dashboard:shift_delete' shift.pk %}" class="d-inline">
          {% csrf_token %}<button type="submit" class="relay-btn" style="font-size:12px;padding:3px 8px;">Remove</button>
        </form>
        <br>
      {% empty %}
        <span style="color:#9A8D7E;">Not scheduled</span>
      {% endfor %}
    </div>
    <div class="col-md-2">
      <a class="relay-btn" href="{% url 'dashboard:shift_create' %}?location={{ selected_location.id }}&date={{ selected_date|date:'Y-m-d' }}&employee={{ row.employee.id }}">+ Shift</a>
    </div>
  </div>
  {% empty %}
  <div style="background:#F1EADD;border:1px solid #E4DACB;padding:40px;text-align:center;font-family:'IBM Plex Sans',sans-serif;font-size:15px;color:#9A8D7E;">
    No Provider/MA employees at this location.
  </div>
  {% endfor %}
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Add the create/edit form template**

Create `templates/dashboard/shift_form.html`:
```html
{% extends "base.html" %}
{% block title %}{{ action }} Shift — Relay{% endblock %}

{% block content %}
<div class="d-flex align-items-center mb-4" style="gap:12px;">
  <a href="{% url 'dashboard:shifts' %}" class="relay-btn" style="font-family:'IBM Plex Mono',monospace; font-size:14px; padding:7px 14px;">← Back</a>
  <div>
    <h2 class="page-title" style="margin-bottom:2px;">{{ action }} Shift</h2>
    <span class="section-label">Fill in the details below</span>
  </div>
</div>

<div style="max-width:600px; background:#FBF9F4; border:1px solid #E4DACB; border-radius:0; padding:32px;">
  <form method="post">
    {% csrf_token %}

    {% if not shift %}
    <div class="mb-3">
      <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">
        Employee *
      </label>
      <select name="employee_id" required
              style="width:100%; font-family:'IBM Plex Sans',sans-serif; font-size:15px; color:#2B2521; background:#FBF9F4; border:1px solid #D6CBBA; border-radius:0; padding:9px 12px; outline:none; box-sizing:border-box;">
        <option value="">Select employee...</option>
        {% for emp in employees %}
          <option value="{{ emp.id }}" {% if request.GET.employee == emp.id|stringformat:"i" %}selected{% endif %}>
            {{ emp.name }} — {{ emp.location.name|default:"Unassigned" }}
          </option>
        {% endfor %}
      </select>
    </div>
    {% else %}
    <div class="mb-3">
      <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">Employee</label>
      <div style="font-family:'IBM Plex Sans',sans-serif; font-size:15px; color:#2B2521;">{{ shift.employee.name }}</div>
    </div>
    {% endif %}

    <div class="mb-3">
      <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">
        Date *
      </label>
      <input type="date" name="date" required
             value="{{ shift.date|date:'Y-m-d'|default:preselect_date }}"
             style="width:100%; font-family:'IBM Plex Mono',monospace; font-size:15px; color:#2B2521; background:#FBF9F4; border:1px solid #D6CBBA; border-radius:0; padding:9px 12px; outline:none; box-sizing:border-box;">
    </div>

    <div class="mb-3 d-flex gap-3">
      <div style="flex:1;">
        <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">
          Start Time *
        </label>
        <input type="time" name="start_time" required
               value="{{ shift.start_time|time:'H:i' }}"
               style="width:100%; font-family:'IBM Plex Mono',monospace; font-size:15px; color:#2B2521; background:#FBF9F4; border:1px solid #D6CBBA; border-radius:0; padding:9px 12px; outline:none; box-sizing:border-box;">
      </div>
      <div style="flex:1;">
        <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">
          End Time *
        </label>
        <input type="time" name="end_time" required
               value="{{ shift.end_time|time:'H:i' }}"
               style="width:100%; font-family:'IBM Plex Mono',monospace; font-size:15px; color:#2B2521; background:#FBF9F4; border:1px solid #D6CBBA; border-radius:0; padding:9px 12px; outline:none; box-sizing:border-box;">
      </div>
    </div>

    {% if not shift %}
    <div class="mb-3">
      <label style="font-family:'IBM Plex Mono',monospace; font-size:12px; text-transform:uppercase; letter-spacing:0.08em; color:#9A8D7E; display:block; margin-bottom:8px;">
        Repeat for next N weeks
      </label>
      <input type="number" name="repeat_weeks" min="0" max="52" value="0"
             style="width:120px; font-family:'IBM Plex Mono',monospace; font-size:15px; color:#2B2521; background:#FBF9F4; border:1px solid #D6CBBA; border-radius:0; padding:9px 12px; outline:none; box-sizing:border-box;">
      <span style="font-family:'IBM Plex Sans',sans-serif; font-size:12px; color:#9A8D7E; display:block; margin-top:6px;">
        0 = just this date. Creates one independent shift row per week, same weekday/time.
      </span>
    </div>
    {% endif %}

    <div style="border-top:1px solid #E4DACB; margin:24px 0;"></div>

    <div style="display:flex; gap:10px;">
      <button type="submit" class="relay-btn relay-btn-primary">Save Shift</button>
      <a href="{% url 'dashboard:shifts' %}" class="relay-btn">Cancel</a>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: Add the sidebar nav link**

In `templates/base.html`, insert a new nav link after the Leaves link (after line 591's closing `</a>`, before the SMS Logs link at line 592):
```html
      <a class="nav-link {% if 'shift' in request.resolver_match.url_name %}active{% endif %}" href="{% url 'dashboard:shifts' %}">
        <i class="bi bi-clock"></i>Shifts
      </a>
```

- [ ] **Step 4: Manually verify end-to-end**

Run: `python manage.py runserver`

In a browser, log in to the dashboard and:
1. Click "Shifts" in the sidebar → confirm the page loads and prompts to select a location and date.
2. Select a location and today's date → confirm the Provider/MA employees at that location list with "Not scheduled".
3. Click "+ Add Shift" → fill in an employee, date, start/end time, leave repeat at 0 → save → confirm redirect back to the day view showing the new shift.
4. Add another shift with "Repeat for next N weeks" = 2 → confirm 3 total `Shift` rows exist for that employee (check via `python manage.py shell -c "from apps.shifts.models import Shift; print(Shift.objects.count())"` or Django admin at `/admin/shifts/shift/`).
5. Click "Edit" on a shift, change the time, save → confirm the change is reflected.
6. Click "Remove" on a shift → confirm it disappears from the list.
7. Go to the Leaves page and submit a leave decision for an employee who now has (or lacks) a shift on the relevant date → confirm the ratio snapshot shown reflects shift-based counting (an employee with no shift that day should not appear as "on duty" in the before/after counts).

Expected: all seven checks behave as described, no server errors in the console.

- [ ] **Step 5: Commit**

```bash
git add templates/dashboard/shifts.html templates/dashboard/shift_form.html templates/base.html
git commit -m "feat: shift assignment UI and navigation"
```

---

## Self-Review Notes

- **Spec coverage:** `Shift` model (Task 1) ✓; ratio engine change with the "no shift = not counted, any shift on the date = counted for the day" rule and no time-of-day matching (Task 2) ✓; dashboard day-view + add/edit/delete + repeat-N-weeks bulk create (Tasks 3-4) ✓; admin registration (Task 1, Step 7) ✓; out-of-scope items (recurrence templates, overlap validation, trading, SMS, self-service) correctly excluded from all tasks.
- **Type consistency:** `Shift` field names (`employee`, `date`, `start_time`, `end_time`, `created_by`) are used identically across Task 1 (model), Task 2 (ratio engine query), Task 3 (views), and Task 4 (templates). URL names (`dashboard:shifts`, `dashboard:shift_create`, `dashboard:shift_edit`, `dashboard:shift_delete`) match between Task 3's `urls.py` and Task 4's templates.
