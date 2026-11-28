from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, UpdateView

from .forms import MeterReadingForm, TariffBandForm, WaterBillForm, WaterMeterForm
from .models import MeterReading, TariffBand, WaterBill, WaterMeter
from .services.anomaly import analyze as analyze_readings

MODULE = {"module_label": "Consommation", "module_url": reverse_lazy("consumption:dashboard")}


class FormPageMixin(PermissionRequiredMixin):
    """Titre, fil d'Ariane et lien « Annuler » pour la page de formulaire commune."""

    page_title = ""
    cancel_url = None

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(MODULE, page_title=self.page_title, cancel_url=self.cancel_url or MODULE["module_url"])
        return ctx

    def form_valid(self, form):
        messages.success(self.request, "Enregistré.")
        return super().form_valid(form)


@login_required
def meter_list(request):
    meters = (WaterMeter.objects.select_related("zone", "zone__site")
              .annotate(last_reading_at=Max("readings__recorded_at"), reading_count=Count("readings"),
                        anomaly_count=Count("readings", filter=Q(readings__is_anomaly=True))))
    return render(request, "consumption/meter_list.html", {"meters": meters})


@login_required
def dashboard(request):
    return render(request, "consumption/dashboard.html", {
        "meter_count": WaterMeter.objects.count(),
        "reading_count": MeterReading.objects.count(),
        "bill_count": WaterBill.objects.count(),
        "anomaly_count": MeterReading.objects.filter(is_anomaly=True).count(),
        "recent_bills": WaterBill.objects.select_related("meter").order_by("-period_end")[:5],
    })


class MeterCreateView(FormPageMixin, CreateView):
    permission_required = "consumption.add_watermeter"
    model = WaterMeter
    form_class = WaterMeterForm
    template_name = "consumption/form.html"
    page_title = "Nouveau compteur"
    cancel_url = reverse_lazy("consumption:meter_list")

    def get_initial(self):
        return {"zone": self.request.GET.get("zone")}

    def get_success_url(self):
        return reverse("consumption:meter_detail", args=[self.object.pk])


meter_create = MeterCreateView.as_view()


class MeterUpdateView(FormPageMixin, UpdateView):
    permission_required = "consumption.change_watermeter"
    model = WaterMeter
    form_class = WaterMeterForm
    template_name = "consumption/form.html"

    def get_context_data(self, **kwargs):
        self.page_title = f"Modifier le compteur {self.object.serial_number}"
        self.cancel_url = reverse("consumption:meter_detail", args=[self.object.pk])
        return super().get_context_data(**kwargs)

    def get_success_url(self):
        return reverse("consumption:meter_detail", args=[self.object.pk])


meter_update = MeterUpdateView.as_view()


class ReadingCreateView(FormPageMixin, CreateView):
    permission_required = "consumption.add_meterreading"
    model = MeterReading
    form_class = MeterReadingForm
    template_name = "consumption/form.html"
    page_title = "Nouveau relevé"

    def get_initial(self):
        return {"meter": self.request.GET.get("meter")}

    def form_valid(self, form):
        response = super().form_valid(form)
        result = analyze_readings([self.object.meter])  # détection de fuites sur tout le compteur
        self.object.refresh_from_db()
        if self.object.is_anomaly:
            messages.warning(self.request, "Consommation inhabituelle sur ce relevé : fuite possible, à vérifier.")
        if result["incidents_opened"]:
            messages.warning(self.request, "Un incident de fuite a été ouvert automatiquement (Qualité & fuites).")
        self.object.meter.forecast_consumption()
        return response

    def get_success_url(self):
        return reverse("consumption:meter_detail", args=[self.object.meter_id])


reading_create = ReadingCreateView.as_view()


class TariffCreateView(FormPageMixin, CreateView):
    permission_required = "consumption.add_tariffband"
    model = TariffBand
    form_class = TariffBandForm
    template_name = "consumption/form.html"
    page_title = "Nouvelle tranche tarifaire"
    success_url = cancel_url = reverse_lazy("consumption:tariff_list")


tariff_create = TariffCreateView.as_view()


class BillCreateView(FormPageMixin, CreateView):
    permission_required = "consumption.add_waterbill"
    model = WaterBill
    form_class = WaterBillForm
    template_name = "consumption/form.html"
    page_title = "Nouvelle facture"
    success_url = cancel_url = reverse_lazy("consumption:bill_list")

    def get_initial(self):
        return {"meter": self.request.GET.get("meter")}

    def form_valid(self, form):
        response = super().form_valid(form)
        self.object.calculate_amounts()
        return response


bill_create = BillCreateView.as_view()


@login_required
def tariff_list(request):
    return render(request, "consumption/tariff_list.html", {"tariffs": TariffBand.objects.all()})


@login_required
def bill_list(request):
    return render(request, "consumption/bill_list.html", {"bills": WaterBill.objects.select_related("meter", "sonede_band", "onas_band")})


@login_required
def meter_detail(request, pk):
    meter = get_object_or_404(WaterMeter.objects.select_related("zone", "zone__site"), pk=pk)
    readings = list(meter.readings.order_by("recorded_at", "pk"))
    rows, previous = [], None
    for reading in readings:
        rows.append({"reading": reading, "volume": reading.index_m3 - previous.index_m3 if previous else None})
        previous = reading
    return render(request, "consumption/meter_detail.html", {
        "meter": meter, "rows": rows[::-1], "last_reading": readings[-1] if readings else None,
        "bills": meter.bills.all()[:5],
    })


@login_required
@permission_required("consumption.add_meterreading", raise_exception=True)
@require_POST
def meter_import(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    if "file" not in request.FILES:
        messages.error(request, "Choisissez un fichier CSV à importer.")
        return redirect("consumption:meter_detail", pk=meter.pk)
    try:
        imported = meter.import_csv_readings(request.FILES["file"])
    except ValidationError as exc:
        messages.error(request, "Import refusé, rien n'a été enregistré : " + " ".join(exc.messages))
        return redirect("consumption:meter_detail", pk=meter.pk)
    result = analyze_readings([meter])
    meter.forecast_consumption()
    skipped = " (relevés déjà présents ignorés)" if not imported else ""
    messages.success(request, f"{len(imported)} relevé(s) importé(s){skipped}.")
    if result["anomalies"]:
        messages.warning(request, f"{result['anomalies']} relevé(s) avec une consommation inhabituelle : fuite possible, à vérifier.")
    if result["incidents_opened"]:
        messages.warning(request, "Le dernier relevé est inhabituel : un incident de fuite a été ouvert (Qualité & fuites).")
    return redirect("consumption:meter_detail", pk=meter.pk)
