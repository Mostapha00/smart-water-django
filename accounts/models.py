"""
Profils utilisateurs partagés par les 4 modules (classe « User » du diagramme UML).

⚠️ Modèles PARTAGÉS : toute modification se décide avec toute l'équipe,
car MaintenanceWork, LeakIncident, WaterSavingsProject et WaterAuditReport en dépendent.

La connexion utilise le User standard de Django ; chaque profil peut y être relié
par le champ `account` (optionnel, pour garder des profils sans compte de connexion).
"""
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    """Classe abstraite « User » du diagramme : champs communs à tous les profils."""

    account = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_profile",
        verbose_name="compte de connexion",
    )
    name = models.CharField("nom", max_length=100)
    first_name = models.CharField("prénom", max_length=100)
    email = models.EmailField("e-mail", unique=True)
    phone = models.CharField("téléphone", max_length=20, blank=True)
    active = models.BooleanField("actif", default=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ["name", "first_name"]

    def display_identity(self) -> str:
        return f"{self.first_name} {self.name}".strip()

    def __str__(self) -> str:
        return self.display_identity()


class NetworkTechnician(UserProfile):
    """Technicien réseau : maintenance et diagnostic."""

    staff_id = models.CharField("matricule", max_length=30, unique=True)
    specialty = models.CharField("spécialité", max_length=100, blank=True)

    class Meta(UserProfile.Meta):
        verbose_name = "technicien réseau"
        verbose_name_plural = "techniciens réseau"

    def schedule_maintenance(self, equipment, scheduled_at, maintenance_type="preventive", summary=""):
        """Crée une intervention pour ce technicien sur une canalisation ou une pompe."""
        from infrastructure.models import MaintenanceWork, WaterPipe, WaterPump

        work = MaintenanceWork(
            technician=self,
            pipe=equipment if isinstance(equipment, WaterPipe) else None,
            pump=equipment if isinstance(equipment, WaterPump) else None,
            scheduled_at=scheduled_at,
            maintenance_type=maintenance_type,
            work_summary=summary,
        )
        work.full_clean()
        work.save()
        return work


class AuditManager(UserProfile):
    """Gestionnaire d'audit : budgets, projets d'économie, rapports (Student 4)."""

    staff_id = models.CharField("matricule", max_length=30, unique=True)
    organization = models.CharField("organisation", max_length=150, blank=True)

    class Meta(UserProfile.Meta):
        verbose_name = "gestionnaire d'audit"
        verbose_name_plural = "gestionnaires d'audit"

    def approve_budget(self):
        # À implémenter par Student 4 (validation d'un WaterAuditReport).
        raise NotImplementedError("approve_budget() : à implémenter dans le module sustainability.")
