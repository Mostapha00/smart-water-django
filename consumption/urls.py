from django.urls import path

from . import api

app_name = "consumption"

urlpatterns = [path("", api.index, name="api_index")]

for collection, singular in (("meters", "meter"), ("readings", "reading"), ("tariffs", "tariff"), ("bills", "bill")):
    urlpatterns += [
        path(f"api/{collection}/", api.resource, {"resource": collection}, name=f"{singular}_list"),
        path(f"api/{collection}/<int:pk>/", api.resource, {"resource": collection}, name=f"{singular}_detail"),
    ]

urlpatterns += [
    path("api/meters/<int:pk>/import/", api.import_csv, name="meter_import"),
    path("api/meters/<int:pk>/forecast/", api.forecast, name="meter_forecast"),
    path("api/meters/<int:pk>/consumption/", api.consumption, name="meter_consumption"),
    path("api/bills/<int:pk>/issue/", api.issue, name="bill_issue"),
]
