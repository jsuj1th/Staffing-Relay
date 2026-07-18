from django import forms
from datetime import time, datetime
from apps.leaves.models import Leave
from apps.accounts.models import Employee
from apps.shifts.models import Shift

# Generate 30-minute time choices (7am - 6pm only)
TIME_CHOICES = [('', 'Select time...')]
for hour in range(7, 19):  # 7am to 6pm (18:00)
    for minute in [0, 30]:
        t = time(hour, minute)
        time_str = t.strftime('%H:%M')
        TIME_CHOICES.append((time_str, time_str))


class LeaveForm(forms.ModelForm):
    """Form for editing leave records in admin dashboard."""

    employee = forms.ModelChoiceField(
        queryset=Employee.objects.filter(is_active=True).order_by('name'),
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    start_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    end_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
    )

    reason = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        required=False,
    )

    status = forms.ChoiceField(
        choices=Leave.Status.choices,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Leave
        fields = ('employee', 'start_date', 'end_date', 'reason', 'status')

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Start date must be before or equal to end date.")

        return cleaned_data


class ShiftForm(forms.ModelForm):
    """Form for creating and editing shift assignments."""

    start_time = forms.ChoiceField(
        choices=TIME_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    end_time = forms.ChoiceField(
        choices=TIME_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    class Meta:
        model = Shift
        fields = ('employee', 'date', 'start_time', 'end_time')
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_time = cleaned_data.get('start_time')
        end_time = cleaned_data.get('end_time')

        # Validate start_time is on 30-min block (times are already HH:MM strings)
        if start_time:
            minutes = int(start_time.split(':')[1])
            if minutes not in [0, 30]:
                raise forms.ValidationError("Start time must be on 30-minute blocks (e.g., 10:00, 10:30)")

        # Validate end_time is on 30-min block
        if end_time:
            minutes = int(end_time.split(':')[1])
            if minutes not in [0, 30]:
                raise forms.ValidationError("End time must be on 30-minute blocks (e.g., 10:00, 10:30)")

        # Validate end_time is after start_time
        if start_time and end_time and start_time >= end_time:
            raise forms.ValidationError("End time must be after start time.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if instance.start_time and isinstance(instance.start_time, str):
            h, m = instance.start_time.split(':')
            instance.start_time = time(int(h), int(m))
        if instance.end_time and isinstance(instance.end_time, str):
            h, m = instance.end_time.split(':')
            instance.end_time = time(int(h), int(m))
        if commit:
            instance.save()
        return instance
