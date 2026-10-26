from django import forms

from .models import MaintenanceWork, Site, WaterPipe, WaterPump, WaterZone

DT_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
DATE_WIDGET = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class BootstrapMixin:
    """Ajoute les classes Bootstrap 5 à tous les champs."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class SiteForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Site
        fields = ["code", "name", "site_type", "governorate", "address"]
        widgets = {"address": forms.Textarea(attrs={"rows": 2})}


class WaterZoneForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WaterZone
        fields = ["site", "code", "name", "usage", "service_pressure_bar", "display_kind", "floors"]


class WaterPipeForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WaterPipe
        fields = ["zone", "reference", "installation_date", "status", "material", "length_m", "diameter_mm", "is_main_supply"]
        widgets = {"installation_date": DATE_WIDGET}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zone"].queryset = WaterZone.objects.select_related("site")


class WaterPumpForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = WaterPump
        fields = ["zone", "reference", "installation_date", "status", "power_kw", "rated_flow_m3_h", "efficiency_pct"]
        widgets = {"installation_date": DATE_WIDGET}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["zone"].queryset = WaterZone.objects.select_related("site")


class MaintenanceWorkForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = MaintenanceWork
        fields = ["technician", "pipe", "pump", "maintenance_type", "scheduled_at", "completed_at", "cost_tnd", "work_summary"]
        widgets = {"scheduled_at": DT_WIDGET, "completed_at": DT_WIDGET, "work_summary": forms.Textarea(attrs={"rows": 3})}
        help_texts = {"pipe": "Choisir une canalisation OU une pompe, pas les deux."}


class CloseWorkForm(BootstrapMixin, forms.Form):
    cost_tnd = forms.DecimalField(label="Coût final (TND)", required=False, min_value=0, decimal_places=3)
    work_summary = forms.CharField(label="Résumé des travaux", required=False, widget=forms.Textarea(attrs={"rows": 3}))
