"""
Module infrastructure — Réseau & équipements (Student 1).

Classes du diagramme : Site, WaterZone, HydraulicEquipment (abstraite),
WaterPipe, WaterPump, MaintenanceWork.

Relations :
- Site 1 *-- 1..* WaterZone           (composition : supprimer un site supprime ses zones)
- WaterZone 1 o-- 0..* équipement      (agrégation : un équipement peut changer de zone)
- MaintenanceWork vise EXACTEMENT UNE cible : une canalisation OU une pompe (XOR)
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

GOVERNORATES = [
    "Ariana", "Béja", "Ben Arous", "Bizerte", "Gabès", "Gafsa", "Jendouba", "Kairouan",
    "Kasserine", "Kébili", "Le Kef", "Mahdia", "La Manouba", "Médenine", "Monastir", "Nabeul",
    "Sfax", "Sidi Bouzid", "Siliana", "Sousse", "Tataouine", "Tozeur", "Tunis", "Zaghouan",
]


class Site(models.Model):
    class SiteType(models.TextChoices):
        SCHOOL = "ecole", "École"
        FACTORY = "usine", "Usine"
        ADMINISTRATION = "administration", "Bâtiment administratif"
        HOSPITAL = "sante", "Établissement de santé"
        OTHER = "autre", "Autre"

    code = models.CharField("code", max_length=30, unique=True)
    name = models.CharField("nom", max_length=150)
    site_type = models.CharField("type", max_length=20, choices=SiteType.choices, default=SiteType.SCHOOL)
    governorate = models.CharField("gouvernorat", max_length=30, choices=[(g, g) for g in GOVERNORATES])
    address = models.TextField("adresse", blank=True)
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "site"

    def __str__(self):
        return f"{self.code} · {self.name}"

    def get_absolute_url(self):
        return reverse("infrastructure:site_detail", args=[self.pk])

    def validate_structure(self) -> None:
        """Un site doit contenir au moins une zone (multiplicité 1..*)."""
        if not self.zones.exists():
            raise ValidationError("Le site doit contenir au moins une zone hydraulique.")

    def equipment(self):
        """Toutes les canalisations et pompes du site (pratique pour les vues)."""
        pipes = list(WaterPipe.objects.filter(zone__site=self).select_related("zone"))
        pumps = list(WaterPump.objects.filter(zone__site=self).select_related("zone"))
        return pipes + pumps

    def calculate_water_balance(self, start, end) -> Decimal:
        """
        Bilan hydrique = volume entré sur le site − somme des volumes comptés par zone.

        Dépend des compteurs et relevés du module consumption (Student 2) et d'un
        compteur général d'arrivée, qui n'existe pas encore dans le modèle.
        """
        raise NotImplementedError(
            "calculate_water_balance() attend les compteurs de Student 2 et un compteur général d'arrivée."
        )


class WaterZone(models.Model):
    class DisplayKind(models.TextChoices):
        BUILDING = "building", "Bâtiment"
        GARDEN = "garden", "Espace extérieur"

    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="zones", verbose_name="site")
    code = models.CharField("code", max_length=30)
    name = models.CharField("nom", max_length=150)
    usage = models.CharField("usage", max_length=100, blank=True)
    service_pressure_bar = models.DecimalField(
        "pression de service (bar)", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Champs d'affichage pour la maquette 3D (extension du diagramme de classes)
    display_kind = models.CharField("forme 3D", max_length=20, choices=DisplayKind.choices, default=DisplayKind.BUILDING)
    floors = models.PositiveSmallIntegerField("étages (3D)", default=1, validators=[MinValueValidator(1), MaxValueValidator(6)])
    pos_x = models.DecimalField("position X (3D)", max_digits=6, decimal_places=2, null=True, blank=True)
    pos_y = models.DecimalField("position Y (3D)", max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["site", "code"]
        verbose_name = "zone hydraulique"
        verbose_name_plural = "zones hydrauliques"
        constraints = [models.UniqueConstraint(fields=["site", "code"], name="unique_zone_code_per_site")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def get_absolute_url(self):
        return reverse("infrastructure:site_detail", args=[self.site_id]) + f"#zone-{self.pk}"

    def validate_meter_coverage(self) -> None:
        """Une zone doit avoir au moins un compteur (WaterMeter du module consumption)."""
        from .services.integration import meters_for_zone

        meters = meters_for_zone(self)
        if meters is None:
            return  # module consumption pas encore implémenté : rien à vérifier
        if not meters:
            raise ValidationError(f"La zone {self} n'a aucun compteur d'eau.")


class HydraulicEquipment(models.Model):
    """Classe abstraite : champs communs aux canalisations et aux pompes."""

    class Status(models.TextChoices):
        IN_SERVICE = "en_service", "En service"
        WATCH = "a_surveiller", "À surveiller"
        BROKEN = "en_panne", "En panne"
        RETIRED = "hors_service", "Hors service"

    zone = models.ForeignKey(WaterZone, on_delete=models.PROTECT, related_name="%(class)ss", verbose_name="zone")
    reference = models.CharField("référence", max_length=40, unique=True)
    installation_date = models.DateField("date d'installation", null=True, blank=True)
    status = models.CharField("statut", max_length=20, choices=Status.choices, default=Status.IN_SERVICE)
    # Sortie IA, toujours stockée avec la version du modèle et la date de calcul
    failure_risk_30d = models.DecimalField(
        "risque de panne à 30 j", max_digits=4, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("1"))],
    )
    model_version = models.CharField("version du modèle", max_length=40, blank=True)
    predicted_at = models.DateTimeField("prédit le", null=True, blank=True)

    kind = ""  # "pipe" ou "pump", défini dans les sous-classes

    class Meta:
        abstract = True
        ordering = ["reference"]

    def __str__(self):
        return self.reference

    @property
    def age_years(self) -> float | None:
        if not self.installation_date:
            return None
        return (timezone.localdate() - self.installation_date).days / 365.25

    def works(self):
        return self.maintenance_works.all()

    def predict_failure_30d(self, save: bool = True) -> Decimal:
        """Calcule le risque de panne à 30 jours et l'enregistre avec la version du modèle."""
        from .services.risk import predict

        risk, version = predict(self)
        self.failure_risk_30d = Decimal(str(round(risk, 3)))
        self.model_version = version
        self.predicted_at = timezone.now()
        if save:
            self.save(update_fields=["failure_risk_30d", "model_version", "predicted_at"])
        return self.failure_risk_30d

    def estimate_replacement_cost(self) -> Decimal:
        raise NotImplementedError  # redéfinie dans WaterPipe et WaterPump (polymorphisme)


class WaterPipe(HydraulicEquipment):
    material = models.CharField("matière", max_length=50)
    length_m = models.DecimalField("longueur (m)", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    diameter_mm = models.PositiveIntegerField("diamètre (mm)", validators=[MinValueValidator(10)])
    is_main_supply = models.BooleanField(
        "conduite d'arrivée", default=False,
        help_text="Canalisation qui part du branchement SONEDE (dessinée depuis l'entrée du site dans la maquette).",
    )

    kind = "pipe"

    class Meta(HydraulicEquipment.Meta):
        verbose_name = "canalisation"

    def get_absolute_url(self):
        return reverse("infrastructure:pipe_detail", args=[self.pk])

    def estimate_replacement_cost(self) -> Decimal:
        """Coût ≈ longueur × (prix matière au mètre, proportionnel au diamètre + pose)."""
        costs = settings.AQUAMIND_REPLACEMENT_COSTS
        per_m_100 = costs["pipe_tnd_per_m_per_100mm"]
        unit = Decimal(str(per_m_100.get(self.material, per_m_100["default"])))
        material_per_m = unit * Decimal(self.diameter_mm) / Decimal(100)
        install_per_m = Decimal(str(costs["pipe_install_tnd_per_m"]))
        return (self.length_m * (material_per_m + install_per_m)).quantize(Decimal("1"))


class WaterPump(HydraulicEquipment):
    power_kw = models.DecimalField("puissance (kW)", max_digits=7, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    rated_flow_m3_h = models.DecimalField("débit nominal (m³/h)", max_digits=8, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])
    efficiency_pct = models.DecimalField(
        "rendement (%)", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
    )

    kind = "pump"

    class Meta(HydraulicEquipment.Meta):
        verbose_name = "pompe"

    def get_absolute_url(self):
        return reverse("infrastructure:pump_detail", args=[self.pk])

    def estimate_replacement_cost(self) -> Decimal:
        """Coût ≈ partie fixe + prix au kW."""
        costs = settings.AQUAMIND_REPLACEMENT_COSTS
        return (Decimal(str(costs["pump_fixed_tnd"])) + self.power_kw * Decimal(str(costs["pump_tnd_per_kw"]))).quantize(Decimal("1"))


class MaintenanceWork(models.Model):
    class MaintenanceType(models.TextChoices):
        PREVENTIVE = "preventive", "Préventive"
        CORRECTIVE = "corrective", "Corrective"

    technician = models.ForeignKey(
        "accounts.NetworkTechnician", on_delete=models.PROTECT, related_name="maintenance_works", verbose_name="technicien",
    )
    pipe = models.ForeignKey(WaterPipe, on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_works", verbose_name="canalisation")
    pump = models.ForeignKey(WaterPump, on_delete=models.CASCADE, null=True, blank=True, related_name="maintenance_works", verbose_name="pompe")
    scheduled_at = models.DateTimeField("prévue le")
    completed_at = models.DateTimeField("terminée le", null=True, blank=True)
    maintenance_type = models.CharField("type", max_length=20, choices=MaintenanceType.choices, default=MaintenanceType.PREVENTIVE)
    cost_tnd = models.DecimalField("coût (TND)", max_digits=10, decimal_places=3, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    work_summary = models.TextField("résumé des travaux", blank=True)

    class Meta:
        ordering = ["-scheduled_at"]
        verbose_name = "intervention de maintenance"
        verbose_name_plural = "interventions de maintenance"
        constraints = [
            models.CheckConstraint(
                condition=(Q(pipe__isnull=False, pump__isnull=True) | Q(pipe__isnull=True, pump__isnull=False)),
                name="maintenance_exactly_one_target",
                violation_error_message="Une intervention vise exactement une cible : une canalisation OU une pompe.",
            ),
            models.CheckConstraint(
                condition=Q(completed_at__isnull=True) | Q(completed_at__gte=models.F("scheduled_at")),
                name="maintenance_completed_after_scheduled",
                violation_error_message="La date de fin ne peut pas précéder la date prévue.",
            ),
        ]

    def __str__(self):
        return f"{self.reference} · {self.target}"

    @property
    def reference(self) -> str:
        return f"MW-{self.pk:04d}" if self.pk else "MW-nouvelle"

    @property
    def target(self):
        return self.pipe or self.pump

    @property
    def is_open(self) -> bool:
        return self.completed_at is None

    def get_absolute_url(self):
        return reverse("infrastructure:work_detail", args=[self.pk])

    def close_work(self, completed_at=None, cost_tnd=None, summary=None, back_in_service=True) -> None:
        """Clôture l'intervention ; une intervention corrective remet l'équipement en service."""
        if not self.is_open:
            raise ValidationError("Cette intervention est déjà clôturée.")
        self.completed_at = completed_at or timezone.now()
        if self.completed_at < self.scheduled_at:
            self.completed_at = self.scheduled_at
        if cost_tnd is not None:
            self.cost_tnd = cost_tnd
        if summary:
            self.work_summary = summary
        self.save()
        target = self.target
        if back_in_service and self.maintenance_type == self.MaintenanceType.CORRECTIVE and target.status != target.Status.RETIRED:
            target.status = target.Status.IN_SERVICE
            target.save(update_fields=["status"])
