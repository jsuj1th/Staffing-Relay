from django import forms
from apps.leaves.models import Leave
from apps.accounts.models import Employee


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
