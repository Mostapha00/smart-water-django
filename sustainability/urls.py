from django.urls import path
from . import views

app_name = "sustainability"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("cibles/", views.TargetList.as_view(), name="target_list"),
    path("cibles/nouveau/", views.TargetCreate.as_view(), name="target_create"),
    path("cibles/<int:pk>/", views.TargetDetail.as_view(), name="target_detail"),
    path("cibles/<int:pk>/modifier/", views.TargetUpdate.as_view(), name="target_update"),
    path("cibles/<int:pk>/supprimer/", views.TargetDelete.as_view(), name="target_delete"),
    path("projets/", views.ProjectList.as_view(), name="project_list"),
    path("projets/nouveau/", views.ProjectCreate.as_view(), name="project_create"),
    path("projets/<int:pk>/", views.ProjectDetail.as_view(), name="project_detail"),
    path("projets/<int:pk>/modifier/", views.ProjectUpdate.as_view(), name="project_update"),
    path("projets/<int:pk>/supprimer/", views.ProjectDelete.as_view(), name="project_delete"),
    path("benefices/", views.BenefitList.as_view(), name="benefit_list"),
    path("benefices/nouveau/", views.BenefitCreate.as_view(), name="benefit_create"),
    path("benefices/<int:pk>/", views.BenefitDetail.as_view(), name="benefit_detail"),
    path("benefices/<int:pk>/modifier/", views.BenefitUpdate.as_view(), name="benefit_update"),
    path("benefices/<int:pk>/supprimer/", views.BenefitDelete.as_view(), name="benefit_delete"),
    path("optimisation/", views.optimize, name="optimize"),
    path("optimisation/<int:pk>/", views.OptimizationDetail.as_view(), name="optimization_detail"),
    path("audit/", views.audit_report, name="audit_report"),
    path("audits/", views.audit_list, name="audit_list"),
    path("audit/<int:pk>/pdf/", views.audit_pdf, name="audit_pdf"),
]
