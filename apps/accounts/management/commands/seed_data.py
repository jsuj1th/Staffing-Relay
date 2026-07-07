"""
Seed command: creates 5 hospitals + representative employees.
Run: python manage.py seed_data [--reset]
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.locations.models import Location, EmployeeLocation
from apps.accounts.models import Employee

User = get_user_model()

LOCATIONS = [
    {"name": "St. Mary's Medical Center", "address": "2233 W Division St", "city": "Chicago", "state": "IL", "phone": "+17735550001"},
    {"name": "Riverside Health Center", "address": "4501 Riverside Dr", "city": "Austin", "state": "TX", "phone": "+15125550002"},
    {"name": "North Valley Hospital", "address": "8100 N Wadsworth Pkwy", "city": "Denver", "state": "CO", "phone": "+17205550003"},
    {"name": "County General Hospital", "address": "2601 E Roosevelt St", "city": "Phoenix", "state": "AZ", "phone": "+16025550004"},
    {"name": "Eastside Medical Clinic", "address": "1500 Moreland Ave SE", "city": "Atlanta", "state": "GA", "phone": "+14045550005"},
]

# Per-location employees (PROVIDER + MA)
# Phone format: +1 XXX 555 YYYY
LOCATION_EMPLOYEES = [
    # Chicago — St. Mary's (index 0)
    [
        ("Dr. Sarah Chen", "+17735550010", "PROVIDER"),
        ("Dr. Marcus Webb", "+17735550011", "PROVIDER"),
        ("Dr. Linda Okafor", "+17735550012", "PROVIDER"),
        ("Dr. James Patel", "+17735550013", "PROVIDER"),
        ("Emma Rodriguez", "+17735550020", "MEDICAL_ASSISTANT"),
        ("Noah Kim", "+17735550021", "MEDICAL_ASSISTANT"),
        ("Priya Sharma", "+17735550022", "MEDICAL_ASSISTANT"),
        ("Tyrell Jackson", "+17735550023", "MEDICAL_ASSISTANT"),
    ],
    # Austin — Riverside (index 1)
    [
        ("Dr. Rachel Torres", "+15125550010", "PROVIDER"),
        ("Dr. Brian Nguyen", "+15125550011", "PROVIDER"),
        ("Dr. Aisha Mahmoud", "+15125550012", "PROVIDER"),
        ("Dr. Kevin Foster", "+15125550013", "PROVIDER"),
        ("Maya Collins", "+15125550020", "MEDICAL_ASSISTANT"),
        ("Ethan Burns", "+15125550021", "MEDICAL_ASSISTANT"),
        ("Sofia Reyes", "+15125550022", "MEDICAL_ASSISTANT"),
        ("Andre Thompson", "+15125550023", "MEDICAL_ASSISTANT"),
    ],
    # Denver — North Valley (index 2)
    [
        ("Dr. Catherine Park", "+17205550010", "PROVIDER"),
        ("Dr. Samuel Wright", "+17205550011", "PROVIDER"),
        ("Dr. Diana Cruz", "+17205550012", "PROVIDER"),
        ("Dr. Omar Hassan", "+17205550013", "PROVIDER"),
        ("Isabella Moore", "+17205550020", "MEDICAL_ASSISTANT"),
        ("Caleb Johnson", "+17205550021", "MEDICAL_ASSISTANT"),
        ("Nadia Petrov", "+17205550022", "MEDICAL_ASSISTANT"),
        ("Damien Lee", "+17205550023", "MEDICAL_ASSISTANT"),
    ],
    # Phoenix — County General (index 3)
    [
        ("Dr. Monica Alvarez", "+16025550010", "PROVIDER"),
        ("Dr. Tyler Simmons", "+16025550011", "PROVIDER"),
        ("Dr. Yuki Tanaka", "+16025550012", "PROVIDER"),
        ("Dr. Carlos Rivera", "+16025550013", "PROVIDER"),
        ("Grace Williams", "+16025550020", "MEDICAL_ASSISTANT"),
        ("Jordan Bell", "+16025550021", "MEDICAL_ASSISTANT"),
        ("Fatima Ali", "+16025550022", "MEDICAL_ASSISTANT"),
        ("Leo Martinez", "+16025550023", "MEDICAL_ASSISTANT"),
    ],
    # Atlanta — Eastside (index 4)
    [
        ("Dr. Patricia Adams", "+14045550010", "PROVIDER"),
        ("Dr. Michael Brown", "+14045550011", "PROVIDER"),
        ("Dr. Serena Scott", "+14045550012", "PROVIDER"),
        ("Dr. Nathan Kim", "+14045550013", "PROVIDER"),
        ("Zoe Clark", "+14045550020", "MEDICAL_ASSISTANT"),
        ("Mason Evans", "+14045550021", "MEDICAL_ASSISTANT"),
        ("Layla Harris", "+14045550022", "MEDICAL_ASSISTANT"),
        ("Owen Nelson", "+14045550023", "MEDICAL_ASSISTANT"),
    ],
]

# Shared staff: (name, phone, type, location_indices, is_primary_index)
SHARED_EMPLOYEES = [
    ("Patricia Cho", "+12015550100", "FRONT_DESK", [0, 1], 0),
    ("David Murray", "+12015550101", "FRONT_DESK", [1, 2], 0),
    ("Alicia Freeman", "+12015550102", "FRONT_DESK", [2, 3], 0),
    ("Trevor Hall", "+12015550103", "FRONT_DESK", [3, 4], 0),
    ("Sandra Pope", "+12015550104", "FRONT_DESK", [0, 4], 0),
    # Management — spans all locations
    ("Director Robert Singh", "+12015550200", "MANAGEMENT", [0, 1, 2, 3, 4], 0),
    ("Director Angela Davis", "+12015550201", "MANAGEMENT", [0, 1, 2, 3, 4], 0),
]


class Command(BaseCommand):
    help = "Seed the database with 5 hospital locations and sample employees."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete all existing data first.")

    def handle(self, *args, **options):
        if options["reset"]:
            self.stdout.write("Resetting employee and location data...")
            EmployeeLocation.objects.all().delete()
            Employee.objects.all().delete()
            Location.objects.all().delete()

        # Create locations
        locations = []
        for loc_data in LOCATIONS:
            loc, created = Location.objects.get_or_create(
                name=loc_data["name"],
                defaults=loc_data,
            )
            locations.append(loc)
            status = "Created" if created else "Exists"
            self.stdout.write(f"  [{status}] {loc.name}")

        # Create location-specific employees
        for loc_idx, emp_list in enumerate(LOCATION_EMPLOYEES):
            loc = locations[loc_idx]
            for name, phone, emp_type in emp_list:
                emp, created = Employee.objects.get_or_create(
                    phone=phone,
                    defaults={"name": name, "employee_type": emp_type, "location": loc},
                )
                if not created:
                    emp.location = loc
                    emp.save()

        self.stdout.write(f"  Created/updated location-specific employees.")

        # Create shared employees
        for name, phone, emp_type, loc_indices, primary_idx in SHARED_EMPLOYEES:
            emp, _ = Employee.objects.get_or_create(
                phone=phone,
                defaults={"name": name, "employee_type": emp_type, "location": None},
            )
            for i, loc_idx in enumerate(loc_indices):
                EmployeeLocation.objects.get_or_create(
                    employee=emp,
                    location=locations[loc_idx],
                    defaults={"is_primary": i == primary_idx},
                )

        self.stdout.write(f"  Created/updated shared employees.")

        # Create superuser if not exists
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser("admin", "admin@hospital.local", "admin123")
            self.stdout.write(self.style.SUCCESS("  Created superuser: admin / admin123"))
        else:
            self.stdout.write("  Superuser 'admin' already exists.")

        total_employees = Employee.objects.count()
        total_locations = Location.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"\nSeeded {total_locations} locations and {total_employees} employees successfully."
        ))
