# Shift Assignment — Design

## Purpose

Relay currently has no concept of scheduling: the leave ratio engine
(`apps/leaves/ratio.py`) treats every `is_active` Provider/MA at a location
as "on duty" on every day, regardless of whether they're actually scheduled
to work. This makes ratio checks inaccurate once locations start using
partial or variable staffing schedules.

This feature adds shift assignment so managers can record who is actually
scheduled to work on a given date, and makes the ratio engine use that
schedule instead of blanket "active = on duty".

## Model

New app: `apps/shifts/`.

```python
class Shift(models.Model):
    employee = models.ForeignKey("accounts.Employee", on_delete=models.CASCADE, related_name="shifts")
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

- No `location` field. A shift's location is always `employee.location`.
  Only PROVIDER/MEDICAL_ASSISTANT employees affect the ratio, and those
  employee types always have a single fixed `location` — no need to
  duplicate it on `Shift`.
- No overlap validation. A manager can create multiple shifts for the same
  employee on the same date (e.g. split shifts) with no conflict checking.
- No recurrence model/template. "Repeat for N weeks" (below) is a bulk-create
  convenience at creation time, not a stored recurring rule — each week's
  shift is its own independent row, editable/deletable individually.

## Ratio engine change

`apps/leaves/ratio.py::get_active_counts(location_id, start_date, end_date, exclude_employee_id=None)`
changes its employee filter:

- **Before:** count all `is_active=True` employees of the relevant type at
  the location, per day.
- **After:** count `is_active=True` employees of the relevant type at the
  location who additionally have at least one `Shift` row for that date.

Rule, stated plainly:
- Employee has a `Shift` row on a given date → counts as on duty for that
  entire date (shift hours are not compared against anything; a leave is
  date-only, so there's no time-of-day matching to do).
- Employee has no `Shift` row on a given date → does not count as on duty,
  regardless of whether that's because nobody at the location has shifts
  for that date yet, or because that specific employee just isn't scheduled.

No fallback to "all active employees" when a location has zero shifts for a
date — that day is genuinely zero-staffed for ratio purposes until shifts
are entered. This is a behavior change to `evaluate_leave`/`get_active_counts`
callers: locations that haven't started using shifts yet will see ratio
checks reject/auto-approve everything as if nobody is on duty, until shifts
are populated for those locations.

This only affects PROVIDER/MEDICAL_ASSISTANT counting. FRONT_DESK/MANAGEMENT
employees already skip ratio checks entirely in `evaluate_leave` and are
unaffected.

## Dashboard UI

New views under `apps/dashboard/` (or a `apps/shifts/views.py` wired into the
dashboard's URL namespace, following whatever pattern `apps/leaves/views.py`
already uses):

- **Day view**: pick a location and date, see all PROVIDER/MA employees at
  that location with a column showing their shift (if any) for that date.
- **Add shift**: employee, start time, end time, optional "repeat this shift
  for the next N weeks" checkbox. Checking it bulk-creates one `Shift` row
  per week (same weekday, same employee, same start/end) for N weeks ahead —
  implemented as a plain loop at save time, not a background job.
- **Edit / delete**: standard per-row edit and delete on individual `Shift`
  rows.

## Admin

Register `Shift` in a `ShiftAdmin` (list by employee/date/start_time/end_time,
filterable by date and employee's location), following the existing
`EmployeeAdmin` pattern in `apps/accounts/admin.py`.

## Out of scope

- Recurring shift templates (only one-off rows + bulk "repeat next N weeks")
- Overlap/conflict validation between shifts
- Shift swapping/trading between employees
- SMS notifications for shift assignment
- Employee self-service view of their own shifts

These can be added later if actually needed; nothing above precludes adding
them without a schema rewrite.
