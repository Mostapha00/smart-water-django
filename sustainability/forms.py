from django import forms

from .models import ConservationTarget, MeasuredBenefit, OptimizationRun, SustainabilityProject

DATE = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class StyledModelForm(forms.ModelForm):
    pass  # les classes Bootstrap sont ajoutées au rendu (templates/aquamind/_fields.html)


class ConservationTargetForm(StyledModelForm):
    class Meta:
        model = ConservationTarget
        fields = "__all__"
        widgets = {"period_start": DATE, "period_end": DATE, "notes": forms.Textarea(attrs={"rows": 3})}
        labels = {"site": "Site", "name": "Nom", "period_start": "Début", "period_end": "Fin",
                  "baseline_m3": "Consommation de référence (m³)", "target_reduction_percent": "Réduction visée (%)",
                  "department": "Service concerné", "notes": "Notes"}

    def clean(self):
        data = super().clean()
        if data.get("period_start") and data.get("period_end") and data["period_end"] < data["period_start"]:
            self.add_error("period_end", "La fin doit être postérieure au début.")
        return data


class SustainabilityProjectForm(StyledModelForm):
    class Meta:
        model = SustainabilityProject
        fields = "__all__"
        widgets = {"start_date": DATE, "completion_date": DATE, "description": forms.Textarea(attrs={"rows": 3})}
        labels = {"site": "Site", "name": "Nom", "project_type": "Type de projet", "description": "Description",
                  "budget_tnd": "Budget (TND)", "expected_savings_m3": "Économie attendue (m³/an)",
                  "expected_annual_savings_tnd": "Économie attendue (TND/an)", "start_date": "Début",
                  "completion_date": "Fin", "status": "Statut"}


class MeasuredBenefitForm(StyledModelForm):
    class Meta:
        model = MeasuredBenefit
        fields = "__all__"
        widgets = {"period_start": DATE, "period_end": DATE, "evidence": forms.Textarea(attrs={"rows": 3})}
        labels = {"project": "Projet", "period_start": "Début", "period_end": "Fin",
                  "measured_savings_m3": "Économie mesurée (m³)", "measured_savings_tnd": "Économie mesurée (TND)",
                  "verified": "Vérifiée", "evidence": "Justificatif (relevés, factures)"}

    def clean(self):
        data = super().clean()
        if data.get("period_start") and data.get("period_end") and data["period_end"] < data["period_start"]:
            self.add_error("period_end", "La fin doit être postérieure au début.")
        return data


class OptimizationRunForm(StyledModelForm):
    class Meta:
        model = OptimizationRun
        fields = ("site", "budget_tnd", "objective")
        labels = {"site": "Site (vide = tous les sites)", "budget_tnd": "Budget disponible (TND)", "objective": "Objectif"}
        help_texts = {"objective": "Les projets proposés, approuvés ou en cours sont comparés ; PuLP choisit la meilleure combinaison."}
