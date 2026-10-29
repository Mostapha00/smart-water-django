from django.apps import apps
from django.db import connection
from django.shortcuts import render
from django.utils import timezone
from django.utils.version import get_version


def dashboard(request):
    settings_dict = connection.settings_dict
    foundation = {
        "app_label": apps.get_app_config("sustainability").label,
        "db_vendor": connection.vendor,
        "db_name": settings_dict.get("NAME"),
        "db_host": settings_dict.get("HOST") or "(local file)",
        "django_version": get_version(),
    }
    return render(
        request,
        "sustainability/dashboard.html",
        {"foundation": foundation, "rendered_at": timezone.now()},
    )
