# SMS Notifications & Menu-Driven Requests

> Smart batching for shift assignments • Leave approval notifications • Guided menu flow for leave requests

---

## 📲 Notification Features

### 1. **Shift Assignment Notifications**

When admins assign shifts, employees get SMS notifications automatically.

**How it works:**
- Admin assigns shift(s) on dashboard
- Notification queued for batching (default: 1 hour)
- Multiple shifts combined into single SMS
- Reduces SMS spam

**Example Message:**
```
📋 RELAY UPDATES:

🕐 SHIFTS ASSIGNED (3):
  • Mon, Jul 25 | 09:00 - 17:00
  • Tue, Jul 26 | 14:00 - 22:00
  • Wed, Jul 27 | 09:00 - 17:00
```

### 2. **Leave Approval/Rejection Notifications**

When leave is approved or rejected, employee gets instant SMS.

**Approved Leave:**
```
✅ Your leave (Jul 25 - Jul 30, 6 days) has been APPROVED ✓
```

**Rejected Leave:**
```
❌ Your leave (Jul 25) could not be approved due to staffing requirements. Contact your manager.
```

### 3. **Notification Batching**

Smart batching to avoid SMS overload:
- **Multiple shift assignments** → Combined into one SMS
- **Mixed notifications** → All types grouped with icons
- **Batch window** → Default 60 minutes (configurable)
- **Immediate option** → Force send now if urgent

---

## 🔧 Technical Details

### Notification Queue Model

```python
class NotificationQueue:
    employee          # Who to notify
    notification_type # SHIFT_ASSIGNED, LEAVE_APPROVED, LEAVE_REJECTED
    message_body      # Content of notification
    is_sent          # Whether SMS was sent
    scheduled_send_at # When to send (for batching)
    created_at       # When queued
```

### Notification Types

```python
NotificationQueue.NotificationType.SHIFT_ASSIGNED
NotificationQueue.NotificationType.LEAVE_APPROVED
NotificationQueue.NotificationType.LEAVE_REJECTED
```

### Usage in Code

**Queue a shift notification (batched):**
```python
from apps.messaging.notifications import notify_shift_assigned

notify_shift_assigned(shift, send_immediately=False)  # Default: batch
```

**Approve leave (send immediately):**
```python
from apps.messaging.notifications import notify_leave_approved

notify_leave_approved(leave, send_immediately=True)
```

**Reject leave:**
```python
from apps.messaging.notifications import notify_leave_rejected

notify_leave_rejected(leave, send_immediately=True)
```

**Manual batch send:**
```python
from apps.messaging.notifications import send_notification_batch

send_notification_batch(employee)  # Send all pending for this employee
```

---

## 📅 Cron Job: Send Due Notifications

To actually send batched notifications, run this periodically (every 5-10 minutes):

```python
from apps.messaging.notifications import send_all_pending_notifications

send_all_pending_notifications()  # Returns number of employees notified
```

**Setup with Django-Q:**
```python
# Add to settings.py
Q_CLUSTER = {
    'name': 'relay',
    'workers': 4,
    'timeout': 500,
    'retry': 600,
    'schedule_attempts': 1,
    'orm': 'default',
}

# Schedule notification sender every 10 minutes
Q_CLUSTER['django_db'] = True
SCHEDULER = {
    'send_notifications': {
        'func': 'apps.messaging.notifications.send_all_pending_notifications',
        'schedule': timedelta(minutes=10),
    }
}
```

---

## 🎯 Menu-Driven Leave Requests

Guide employees through structured leave request via SMS instead of free-form text.

### Request Flow

**User sends:** `LEAVE`  
**Bot responds:** Menu of leave types

```
📋 RELAY LEAVE REQUEST

Reply with leave type:
1 = Sick Leave
2 = Vacation
3 = Personal
4 = Medical
5 = Other

Example: Reply '2' for vacation
```

**User sends:** `2`  
**Bot responds:** Ask for dates

```
📅 ENTER DATES

Format: MMDD-MMDD (range) or MMDD (single day)

Examples:
0725 = July 25 (today or later)
0725-0730 = July 25-30

Or reply CANCEL to abort
```

**User sends:** `0725-0730`  
**Bot responds:** Ask for reason

```
📝 REASON (optional)

Brief reason for leave:
(Or reply SKIP if not needed)
```

**User sends:** `Summer vacation`  
**Bot responds:** Confirmation

```
📋 LEAVE REQUEST SUMMARY

Type: Vacation
Dates: Jul 25 - Jul 30
Duration: 6 days
Reason: Summer vacation

✅ Reply YES to submit
❌ Reply NO to cancel
```

**User sends:** `YES`  
**Bot responds:** Submitted

```
✅ Leave request submitted!

Your request is being processed.
You'll receive an SMS when it's approved or rejected.
```

### Date Input Formats

| Input | Interpreted As |
|-------|----------------|
| `0725` | July 25 (today or later) |
| `1215` | December 15 (next year if past) |
| `0725-0730` | July 25 - July 30 |
| `1225-0105` | Dec 25 - Jan 5 (year boundary) |

### Leave Type Codes

| Code | Type |
|------|------|
| 1 | Sick Leave |
| 2 | Vacation |
| 3 | Personal Leave |
| 4 | Medical Leave |
| 5 | Other |

---

## 🧪 Testing

### Run Notification Tests

```bash
python manage.py test apps.messaging.test_notifications -v 2
```

**Test Coverage:**
- ✅ Notification queuing (batched + immediate)
- ✅ Multiple shifts batched into one SMS
- ✅ Leave approved/rejected notifications
- ✅ Cron job sends due notifications
- ✅ Date parsing (single + range)
- ✅ Confirmation message formatting

**Example:**
```
test_queue_notification_batched ✓
test_queue_notification_immediate ✓
test_batch_multiple_shifts ✓
test_notify_shift_assigned ✓
test_notify_leave_approved ✓
test_notify_leave_rejected ✓
test_send_all_pending_notifications ✓
test_parse_single_date ✓
test_parse_date_range ✓
test_parse_invalid_date ✓
test_build_confirmation_message ✓
```

---

## 📊 Database Schema

### NotificationQueue Table

```
id             | Primary key
employee_id    | FK to Employee
notification_type | SHIFT_ASSIGNED, LEAVE_APPROVED, etc.
message_body   | Text content
related_object_id | ID of Shift or Leave
is_sent        | Boolean
sent_at        | DateTime when sent
created_at     | DateTime when queued
scheduled_send_at | DateTime when to send (batching)
```

### Indexes

```
(employee_id, is_sent, created_at)  # For finding pending notifications
```

---

## 🔍 Monitoring

### Check Pending Notifications

```python
from apps.messaging.models import NotificationQueue

# Pending for an employee
pending = NotificationQueue.objects.filter(
    employee_id=123,
    is_sent=False,
).count()

# All pending globally
all_pending = NotificationQueue.objects.filter(is_sent=False).count()

# Due notifications (ready to send)
due = NotificationQueue.objects.filter(
    is_sent=False,
    scheduled_send_at__lte=timezone.now(),
).count()
```

### View Sent Notifications

```python
from apps.messaging.models import SmsLog

# Outgoing notifications
outgoing = SmsLog.objects.filter(
    inbound_msg__contains="[Batch notification]"
).order_by("-created_at")[:10]
```

---

## ⚙️ Configuration

### Batch Window (Default: 60 minutes)

Change how long to wait before sending batched notifications:

```python
queue_notification(
    employee=emp,
    notification_type="SHIFT_ASSIGNED",
    message_body="...",
    batch_window_minutes=30,  # Send within 30 minutes
)
```

### Send Immediately

For urgent notifications (leave decisions), send right away:

```python
notify_leave_approved(leave, send_immediately=True)
notify_leave_rejected(leave, send_immediately=True)
```

---

## 🚀 Future Enhancements

- [ ] WhatsApp notifications (parallel to SMS)
- [ ] Push notifications (mobile app)
- [ ] Email digests for managers
- [ ] Two-way conversation support
- [ ] Voice call confirmations
- [ ] Notification preferences per employee
