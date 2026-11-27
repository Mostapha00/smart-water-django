from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import CreateView
from django.urls import reverse_lazy
from django.contrib.auth.mixins import PermissionRequiredMixin

from .forms import MeterReadingForm, TariffBandForm, WaterBillForm, WaterMeterForm
from .models import MeterReading, TariffBand, WaterBill, WaterMeter
from .services.anomaly import analyze as analyze_readings


@login_required
def meter_list(request):
    meters = WaterMeter.objects.select_related("zone", "zone__site").prefetch_related("readings")
    return render(request, "consumption/meter_list.html", {"meters": meters})


@login_required
def dashboard(request):
    meters = WaterMeter.objects.count()
    readings = sum(m.readings.count() for m in WaterMeter.objects.prefetch_related("readings"))
    bills = WaterBill.objects.count()
    return render(request, "consumption/dashboard.html", {"meter_count": meters, "reading_count": readings, "bill_count": bills, "recent_bills": WaterBill.objects.select_related("meter").order_by("-period_end")[:5]})


class MeterCreateView(PermissionRequiredMixin, CreateView):
    permission_required = "consumption.add_watermeter"
    model = WaterMeter
    form_class = WaterMeterForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:meter_list")


meter_create = MeterCreateView.as_view()


class ReadingCreateView(PermissionRequiredMixin, CreateView):
    permission_required = "consumption.add_meterreading"
    model = MeterReading
    form_class = MeterReadingForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:meter_list")

    def form_valid(self, form):
        response = super().form_valid(form)
        if self.object.detect_anomaly():
            messages.warning(self.request, "Consommation inhabituelle sur ce relevé : fuite possible, à vérifier.")
        self.object.meter.forecast_consumption()
        return response


reading_create = ReadingCreateView.as_view()


class TariffCreateView(PermissionRequiredMixin, CreateView):
    permission_required = "consumption.add_tariffband"
    model = TariffBand
    form_class = TariffBandForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:tariff_list")


tariff_create = TariffCreateView.as_view()


class BillCreateView(PermissionRequiredMixin, CreateView):
    permission_required = "consumption.add_waterbill"
    model = WaterBill
    form_class = WaterBillForm
    template_name = "consumption/form.html"
    success_url = reverse_lazy("consumption:bill_list")

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
    return render(request, "consumption/meter_detail.html", {"meter": meter, "readings": meter.readings.all()})


@login_required
@permission_required("consumption.add_meterreading", raise_exception=True)
def meter_import(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    if request.method != "POST" or "file" not in request.FILES:
        return HttpResponseBadRequest("Un fichier CSV est requis.")
    try:
        imported = meter.import_csv_readings(request.FILES["file"])
    except ValidationError as exc:
        return HttpResponseBadRequest("; ".join(exc.messages))
    flagged = analyze_readings([meter])["anomalies"]
    meter.forecast_consumption()
    messages.success(request, f"{len(imported)} relevé(s) importé(s).")
    if flagged:
        messages.warning(request, f"{flagged} relevé(s) avec une consommation inhabituelle : fuite possible, à vérifier.")
    return redirect("consumption:meter_detail", pk=meter.pk)
