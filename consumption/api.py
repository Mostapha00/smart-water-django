"""Session-authenticated JSON endpoints using Django's existing permissions and CSRF."""
from datetime import date
from decimal import Decimal
from functools import wraps
import json

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.http import Http404, JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import ensure_csrf_cookie

from .models import MeterReading, TariffBand, WaterBill, WaterMeter

RESOURCES = {
    "meters": (WaterMeter, ("zone", "serial_number", "customer_category", "installed_on", "active")),
    "readings": (MeterReading, ("meter", "recorded_at", "index_m3", "source")),
    "tariffs": (TariffBand, ("service", "customer_category", "valid_from", "valid_until", "lower_bound_m3", "upper_bound_m3", "price_per_m3_tnd", "fixed_fee_tnd", "reference_period_days", "calculation_mode", "official_source")),
    "bills": (WaterBill, ("meter", "period_start", "period_end", "include_onas")),
}


def endpoint(methods, permission=None):
    """Translate boundary errors once; internal services use Django ValidationError."""
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                response = JsonResponse({"error": "Method not allowed."}, status=405)
                response["Allow"] = ", ".join(methods)
                return response
            if not request.user.is_authenticated:
                return JsonResponse({"error": "Log in through /connexion/ first."}, status=401)
            if permission and not request.user.has_perm(permission):
                return JsonResponse({"error": "Permission denied."}, status=403)
            try:
                return view(request, *args, **kwargs)
            except ValidationError as exc:
                details = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
                return JsonResponse({"error": "Invalid data.", "details": details}, status=400)
            except (Http404, ObjectDoesNotExist):
                return JsonResponse({"error": "Not found."}, status=404)
            except ProtectedError:
                return JsonResponse({"error": "Related records protect this object from deletion."}, status=409)
            except IntegrityError:
                return JsonResponse({"error": "The change conflicts with an existing record or database constraint."}, status=409)
        return wrapped
    return decorate


def _invalid_constant(value):
    raise ValueError(value)


def body(request):
    if request.content_type != "application/json":
        raise ValidationError("Use Content-Type: application/json.")
    if len(request.body) > 65536:
        raise ValidationError("JSON bodies are limited to 64 KiB.")
    try:
        value = json.loads(request.body, parse_float=Decimal, parse_constant=_invalid_constant)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("A valid JSON object is required.") from exc
    if not isinstance(value, dict):
        raise ValidationError("A JSON object is required.")
    return value


def positive_int(value, name, maximum=None):
    if isinstance(value, bool) or not str(value).isdigit():
        raise ValidationError(f"{name} must be a positive integer.")
    value = int(value)
    if value < 1 or maximum is not None and value > maximum:
        raise ValidationError(f"{name} is out of range.")
    return value


def assign(obj, values, allowed):
    unknown = set(values) - set(allowed)
    if unknown:
        raise ValidationError("Unknown or read-only fields: " + ", ".join(sorted(unknown)))
    for name, value in values.items():
        field = obj._meta.get_field(name)
        converted = field.to_python(value)
        if field.get_internal_type() == "DateTimeField" and converted is not None and timezone.is_naive(converted):
            converted = timezone.make_aware(converted)
        setattr(obj, field.attname, converted)


def serialize(obj, detail=False):
    result = {field.name: getattr(obj, field.attname) for field in obj._meta.concrete_fields}
    if isinstance(obj, MeterReading) and detail:
        result["volume_m3"] = obj.calculate_volume()
    return result


def _permission(request, model):
    action = {"GET": "view", "POST": "add", "PATCH": "change", "PUT": "change", "DELETE": "delete"}[request.method]
    return request.user.has_perm(f"consumption.{action}_{model._meta.model_name}")


@ensure_csrf_cookie
@endpoint(["GET"])
def index(request):
    return JsonResponse({
        "module": "Student 2: consumption and billing", "authentication": "Django session",
        "csrf_token": get_token(request), "api": {
            key: reverse(f"consumption:{key[:-1] if key != 'tariffs' else 'tariff'}_list")
            for key in RESOURCES
        },
        "documentation": "consumption/README.md", "admin": "/admin/consumption/",
        "billing": "Configurable estimates in TND, excluding taxes. No official rates are bundled.",
    })


@endpoint(["GET", "POST", "PATCH", "PUT", "DELETE"])
def resource(request, resource, pk=None):
    model, writable = RESOURCES[resource]
    if request.method in {"PATCH", "PUT", "DELETE"} and pk is None or request.method == "POST" and pk is not None:
        return JsonResponse({"error": "This method is not available on this URL."}, status=405)
    if not _permission(request, model):
        return JsonResponse({"error": "Permission denied."}, status=403)
    if request.method == "GET":
        if pk is not None:
            return JsonResponse(serialize(get_object_or_404(model, pk=pk), detail=True))
        qs = model.objects.all()
        filters = {"site": "zone__site_id", "zone": "zone_id"} if resource == "meters" else {"meter": "meter_id"} if resource in {"readings", "bills"} else {}
        for parameter, lookup in filters.items():
            if parameter in request.GET:
                qs = qs.filter(**{lookup: positive_int(request.GET[parameter], parameter)})
        if resource == "tariffs":
            for name in ("service", "customer_category"):
                if name in request.GET:
                    qs = qs.filter(**{name: request.GET[name]})
        limit = positive_int(request.GET.get("limit", 50), "limit", maximum=200)
        page = positive_int(request.GET.get("page", 1), "page")
        offset = (page - 1) * limit
        return JsonResponse({"count": qs.count(), "page": page, "results": [serialize(item) for item in qs[offset:offset + limit]]})
    with transaction.atomic():
        obj = get_object_or_404(model, pk=pk) if pk is not None else model()
        if request.method == "DELETE":
            obj.delete()
            return JsonResponse({"deleted": True})
        values = body(request)
        assign(obj, values, writable)
        if model is WaterBill:
            for name in ("meter", "period_start", "period_end"):
                if getattr(obj, model._meta.get_field(name).attname) is None:
                    raise ValidationError({name: "This field is required."})
            obj.calculate_amounts()
        else:
            obj.save()
        return JsonResponse(serialize(obj, detail=True), status=201 if pk is None else 200)


@endpoint(["POST"], "consumption.add_meterreading")
def import_csv(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    file = request.FILES.get("file")
    if file is None:
        raise ValidationError("Upload a UTF-8 CSV using the multipart field named file.")
    return JsonResponse(meter.import_csv_readings(file))


@endpoint(["POST"], "consumption.change_watermeter")
def forecast(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    data = body(request)
    if set(data) - {"horizon_days"}:
        raise ValidationError("Only horizon_days may be supplied.")
    return JsonResponse(meter.forecast_consumption(data.get("horizon_days", 30)))


@endpoint(["GET"], "consumption.view_watermeter")
def consumption(request, pk):
    meter = get_object_or_404(WaterMeter, pk=pk)
    try:
        start, end = parse_date(request.GET.get("start", "")), parse_date(request.GET.get("end", ""))
    except ValueError as exc:
        raise ValidationError("start and end must be valid ISO dates.") from exc
    if start is None or end is None:
        raise ValidationError("start and end must be ISO dates: YYYY-MM-DD.")
    volume, first, last = meter.volume_between(start, end)
    return JsonResponse({"meter": meter.pk, "start": start, "end_exclusive": end, "volume_m3": volume,
                         "start_reading": first.pk, "end_reading": last.pk})


@endpoint(["POST"], "consumption.change_waterbill")
def issue(request, pk):
    bill = get_object_or_404(WaterBill, pk=pk)
    bill.issue_bill()
    return JsonResponse(serialize(bill, detail=True))
