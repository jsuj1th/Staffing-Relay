from django.db import migrations


def backfill(apps, schema_editor):
    """Existing shifts predate Shift.location: adopt the employee's home location.
    Shared staff (no home location) stay null — which location they worked was
    never recorded, so Shift.site keeps falling back as before."""
    Shift = apps.get_model("shifts", "Shift")
    todo = []
    for shift in Shift.objects.filter(
        location__isnull=True, employee__location__isnull=False
    ).select_related("employee"):
        shift.location_id = shift.employee.location_id
        todo.append(shift)
    Shift.objects.bulk_update(todo, ["location"], batch_size=500)


def unbackfill(apps, schema_editor):
    # Reversing only clears what backfill could have set.
    apps.get_model("shifts", "Shift").objects.update(location=None)


class Migration(migrations.Migration):
    dependencies = [("shifts", "0003_shift_location")]
    operations = [migrations.RunPython(backfill, unbackfill)]
