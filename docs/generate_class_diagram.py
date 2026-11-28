"""Régénère le diagramme de classes du dossier de validation à partir des vrais modèles Django.

    python docs/generate_class_diagram.py ../validation_dossier.html

Remplace dans le fichier HTML : les données des classes (champs, types, liens, méthodes), le source
Mermaid de la vue complète, les vues par module, les champs résumés et les descriptions.
Les verbes des liens, les descriptions et la mise en page des vues sont définis ci-dessous.
"""
import inspect
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOSSIER = os.path.abspath(sys.argv[1])
sys.path.insert(0, REPO)
os.chdir(REPO)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from django.apps import apps  # noqa: E402
from django.contrib.contenttypes.fields import GenericForeignKey  # noqa: E402
from django.db import models  # noqa: E402

APPS = {"accounts": "core", "infrastructure": "infrastructure", "consumption": "consumption",
        "quality_leaks": "quality_leaks", "sustainability": "sustainability"}
ORDER = ["UserProfile", "NetworkTechnician", "AuditManager", "Site", "WaterZone", "HydraulicEquipment", "WaterPipe",
         "WaterPump", "MaintenanceWork", "WaterMeter", "MeterReading", "TariffBand", "WaterBill", "WaterQualityTest",
         "AlertRule", "LeakIncident", "ConservationTarget", "SustainabilityProject", "MeasuredBenefit",
         "OptimizationRun", "AuditReport"]
# 3D-display fields of WaterZone: presentation only, not part of the domain model.
SKIP_FIELDS = {"id", "display_kind", "floors", "pos_x", "pos_y", "meter_content_type", "meter_object_id",
               "trigger_reading_content_type", "trigger_reading_object_id"}
SKIP_METHODS = {"get_absolute_url", "clean", "save", "delete", "full_clean"}
TYPES = {"CharField": "String", "TextField": "Text", "DecimalField": "Decimal", "DateField": "Date",
         "DateTimeField": "DateTime", "BooleanField": "Boolean", "IntegerField": "Integer",
         "PositiveIntegerField": "Integer", "PositiveSmallIntegerField": "Integer", "PositiveBigIntegerField": "Integer",
         "FloatField": "Float", "JSONField": "JSON", "EmailField": "Email", "URLField": "URL", "ForeignKey": "FK",
         "OneToOneField": "FK", "ManyToManyField": "Set"}
VERBS = {("Site", "WaterZone"): "contains", ("WaterZone", "HydraulicEquipment"): "groups",
         ("NetworkTechnician", "MaintenanceWork"): "carries out", ("WaterPipe", "MaintenanceWork"): "targets pipe",
         ("WaterPump", "MaintenanceWork"): "targets pump", ("WaterZone", "WaterMeter"): "groups",
         ("WaterMeter", "MeterReading"): "records", ("WaterMeter", "WaterBill"): "is billed in",
         ("WaterZone", "WaterQualityTest"): "is tested by", ("WaterMeter", "LeakIncident"): "reveals",
         ("MeterReading", "LeakIncident"): "triggers", ("WaterQualityTest", "LeakIncident"): "reveals",
         ("AlertRule", "LeakIncident"): "flags", ("NetworkTechnician", "LeakIncident"): "investigates",
         ("WaterPipe", "LeakIncident"): "suspected pipe", ("WaterPump", "LeakIncident"): "suspected pump",
         ("Site", "ConservationTarget"): "sets", ("Site", "SustainabilityProject"): "has",
         ("SustainabilityProject", "MeasuredBenefit"): "is measured by", ("Site", "OptimizationRun"): "is optimised in",
         ("Site", "AuditReport"): "is audited in"}
AGGREGATIONS = {("WaterZone", "HydraulicEquipment"), ("WaterZone", "WaterMeter")}
DESCRIPTIONS = {
    "UserProfile": "Shared information for both professional profiles. A profile can be linked to a Django login account.",
    "NetworkTechnician": "The person who maintains the network and investigates incidents.",
    "AuditManager": "The person responsible for audits and budgets (profile only: reports and optimisations record the login account that created them).",
    "Site": "The location being monitored, such as a school, factory, or municipal building.",
    "WaterZone": "Part of a site, such as a building or a section of its water network.",
    "HydraulicEquipment": "Shared information for pipes and pumps.",
    "WaterPipe": "A pipe that carries water.",
    "WaterPump": "Equipment that moves water through the network.",
    "MaintenanceWork": "Maintenance work on exactly one pipe or pump.",
    "WaterMeter": "A water meter whose readings are entered manually or imported from CSV.",
    "MeterReading": "A cumulative meter reading at a specific date and time, with its leak-detection result.",
    "TariffBand": "A SONEDE or ONAS price band for a customer category and validity period.",
    "WaterBill": "Water consumed and the amounts calculated for a billing period, with a snapshot of the tariffs used.",
    "WaterQualityTest": "Laboratory measurements for a water sample and its potability index.",
    "AlertRule": "A versioned threshold to check, such as maximum turbidity.",
    "LeakIncident": "A suspected leak or water-quality problem, tracked from opening to resolution. It starts from a meter, a quality test, or both.",
    "ConservationTarget": "A water-reduction target for a site and a period, compared with measured consumption.",
    "SustainabilityProject": "A proposed project to save water (network repair, greywater, rainwater, low-flow equipment).",
    "MeasuredBenefit": "Savings actually measured after a project, kept separate from estimated savings.",
    "OptimizationRun": "A budget optimisation: the combination of projects chosen by PuLP within a budget.",
    "AuditReport": "A dated audit of a site and period; its indicators are frozen in a snapshot and exported as PDF.",
}
ESSENTIAL = {
    "UserProfile": ["name", "first_name", "email"], "NetworkTechnician": ["staff_id", "specialty"],
    "AuditManager": ["staff_id", "organization"], "Site": ["code", "name", "governorate"],
    "WaterZone": ["code", "name", "service_pressure_bar"], "HydraulicEquipment": ["reference", "status", "failure_risk_30d"],
    "WaterPipe": ["material", "length_m", "diameter_mm"], "WaterPump": ["power_kw", "rated_flow_m3_h", "efficiency_pct"],
    "MaintenanceWork": ["scheduled_at", "maintenance_type", "cost_tnd"],
    "WaterMeter": ["serial_number", "customer_category", "forecast_m3"], "MeterReading": ["recorded_at", "index_m3", "is_anomaly"],
    "TariffBand": ["service", "price_per_m3_tnd", "fixed_fee_tnd"], "WaterBill": ["period_start", "volume_m3", "total_amount_tnd"],
    "WaterQualityTest": ["sampled_at", "ph", "turbidity_ntu"], "AlertRule": ["name", "parameter", "threshold"],
    "LeakIncident": ["reference", "status", "opened_at"],
    "ConservationTarget": ["name", "baseline_m3", "target_reduction_percent"],
    "SustainabilityProject": ["name", "budget_tnd", "expected_savings_m3"],
    "MeasuredBenefit": ["period_start", "measured_savings_m3", "verified"],
    "OptimizationRun": ["budget_tnd", "solver", "projected_savings_m3"], "AuditReport": ["period_start", "period_end", "snapshot"],
}
STROKES = {"core": "#64748b", "infrastructure": "#0077b6", "consumption": "#17876f", "quality_leaks": "#b97422", "sustainability": "#7461c5"}


def collect():
    classes = {}
    for model in apps.get_models():
        label = model._meta.app_label
        if label not in APPS:
            continue
        for base in model.__mro__[1:]:
            if isinstance(base, type) and issubclass(base, models.Model) and base is not models.Model and base._meta.abstract:
                classes.setdefault(base.__name__, (base, APPS[label]))
        classes[model.__name__] = (model, APPS[label])
    missing = set(classes) - set(ORDER)
    assert not missing, f"Add to ORDER: {missing}"
    return [(name, *classes[name]) for name in ORDER if name in classes]


def parent_of(cls):
    for base in cls.__mro__[1:]:
        if isinstance(base, type) and issubclass(base, models.Model) and base is not models.Model and base._meta.abstract:
            return base
    return None


def own_fields(cls):
    parent = parent_of(cls)
    inherited = {f.name for f in parent._meta.fields} if parent else set()
    fields = [f for f in cls._meta.fields if f.name not in inherited and f.name not in SKIP_FIELDS]
    fields += [f for f in cls._meta.many_to_many]
    generic = [f for f in cls._meta.private_fields if isinstance(f, GenericForeignKey)]
    return fields, generic


def target_name(field):
    model = field.related_model
    if isinstance(model, str):  # lazy reference on an abstract model, e.g. "auth.User"
        model = apps.get_model(model) if "." in model else apps.get_model(field.model._meta.app_label, model)
    if model._meta.app_label == "auth":
        return "Django login account"
    return model.__name__


DERIVED = {
    "target_m3": ("Decimal", "Volume visé = référence × (1 − réduction %)."),
    "payback_months": ("Decimal", "Retour sur investissement = budget ÷ économie annuelle × 12 (vide si l'économie en TND est nulle)."),
}


def methods_of(cls):
    out = [{"name": "/" + name, "args": "", "returns": DERIVED[name][0], "doc": "Attribut calculé. " + DERIVED[name][1]}
           for name, value in cls.__dict__.items() if isinstance(value, property) and name in DERIVED]
    for name, value in cls.__dict__.items():
        if name.startswith("_") or name in SKIP_METHODS or not inspect.isfunction(value):
            continue
        sig = inspect.signature(value)
        args = ", ".join(p for p in sig.parameters if p != "self" and sig.parameters[p].kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD))
        ret = sig.return_annotation
        returns = "" if ret is inspect.Signature.empty else getattr(ret, "__name__", str(ret)).replace("'", "")
        doc = " ".join((inspect.getdoc(value) or "").split())
        out.append({"name": name, "args": args, "returns": returns, "doc": doc or "—"})
    return out


def build():
    schema, relations, mermaid_classes = [], [], []
    for name, cls, module in collect():
        parent = parent_of(cls)
        fields, generic = own_fields(cls)
        entries = []
        for f in fields:
            ftype = TYPES.get(f.get_internal_type(), f.get_internal_type())
            target = target_name(f) if f.is_relation else None
            entries.append({"name": f.name, "type": ftype, "nullable": bool(getattr(f, "null", False) or getattr(f, "blank", False) and f.is_relation),
                            "target": target})
        for g in generic:
            target = {"meter": "WaterMeter", "trigger_reading": "MeterReading"}.get(g.name, "any")
            entries.append({"name": g.name, "type": "FK", "nullable": True, "target": target})
        schema.append({"name": name, "module": module, "abstract": cls._meta.abstract, "parent": parent.__name__ if parent else None,
                       "description": DESCRIPTIONS[name], "fields": entries, "methods": methods_of(cls)})
        # Mermaid box: own attributes only; links (FKs to our classes) are drawn as lines.
        lines = [f"class {name} {{"]
        if cls._meta.abstract:
            lines.append("  <<Abstract>>")
        for e in entries:
            if e["type"] in ("FK", "Set") and e["target"] in ORDER:
                continue
            ftype = "LoginAccount" if e["target"] == "Django login account" else e["type"]
            lines.append(f"  +{ftype} {e['name']}")
        for m in schema[-1]["methods"]:
            if m["name"].startswith("/"):
                lines.insert(len(lines), f"  +{m['returns']} {m['name']}")
            else:
                lines.append(f"  +{m['name']}() {m['returns']}".rstrip())
        lines.append("}")
        mermaid_classes.append("\n".join(lines))
        # Relations
        if parent:
            relations.append(f"{parent.__name__} <|-- {name}")
        for e in entries:
            if e["target"] not in ORDER or e["type"] not in ("FK", "Set"):
                continue
            source = e["target"]
            # FKs declared on the abstract parent are drawn once, from the parent.
            if parent and e["name"] in {f.name for f in parent._meta.fields}:
                continue
            owner = "HydraulicEquipment" if (cls._meta.abstract and name == "HydraulicEquipment") else name
            key = (source, owner)
            if e["type"] == "Set":
                relations.append(f'{owner} "0..*" --> "0..*" {source} : selects')
                continue
            field = next((f for f in cls._meta.fields if f.name == e["name"]), None)
            cascade = field is not None and field.remote_field.on_delete is models.CASCADE
            kind = "o--" if key in AGGREGATIONS else ("*--" if cascade and not e["nullable"] else "-->")
            verb = VERBS.get(key) or ("SONEDE tariff" if e["name"] == "sonede_band" else "ONAS tariff" if e["name"] == "onas_band" else e["name"])
            left = "0..1" if e["nullable"] else "1"
            right = "1..*" if key == ("Site", "WaterZone") else "0..*"  # règle métier : validate_structure()
            relations.append(f'{source} "{left}" {kind} "{right}" {owner} : {verb}')
    notes = ['note for MaintenanceWork "Exactly one target: a pipe OR a pump"',
             'note for LeakIncident "Source: a meter, a quality test, or both<br>Suspect: a pipe OR a pump OR none"']
    styles = [f"style {s['name']} fill:#f5faff,stroke:{STROKES[s['module']]},stroke-width:2px,color:#142d45" for s in schema]
    source = "classDiagram\ndirection TB\n" + "\n".join(mermaid_classes) + "\n" + "\n".join(dict.fromkeys(relations)) + "\n" + "\n".join(notes) + "\n" + "\n".join(styles)
    return schema, source, len([r for r in dict.fromkeys(relations)])


schema, source, n_links = build()
for s in schema:
    names = {f["name"] for f in s["fields"]}
    parent = next((p for p in schema if p["name"] == s["parent"]), None)
    names |= {f["name"] for f in parent["fields"]} if parent else set()
    bad = [n for n in ESSENTIAL[s["name"]] if n not in names]
    assert not bad, (s["name"], bad)
html = open(DOSSIER, encoding="utf-8").read()


def replace_between(text, start, end, new):
    i = text.index(start) + len(start)
    j = text.index(end, i)
    return text[:i] + new + text[j:]


html = replace_between(html, '<script type="application/json" id="model-schema">', "</script>", json.dumps(schema, ensure_ascii=False))
html = replace_between(html, '<script type="text/plain" id="uml-source">', "</script>", source)
html = replace_between(html, "const essential=", ";\n", json.dumps(ESSENTIAL, ensure_ascii=False))
html = replace_between(html, "const simpleDescriptions=", ";\n", json.dumps(DESCRIPTIONS, ensure_ascii=False))
html = replace_between(html, "const order=", ";", json.dumps(ORDER))
configs = """{
 infrastructure:{title:'Network & equipment',count:'6 classes',nodes:{Site:[20,30],WaterZone:[390,30],HydraulicEquipment:[760,30],MaintenanceWork:[20,280],WaterPipe:[390,280],WaterPump:[760,280]},explanation:'A site contains zones. Each zone groups equipment: pipes or pumps. A maintenance job concerns exactly one pipe or pump.'},
 consumption:{title:'Consumption & billing',count:'4 classes',nodes:{WaterMeter:[20,30],MeterReading:[760,30],TariffBand:[20,280],WaterBill:[760,280]},explanation:'A meter records cumulative readings; consumption is the difference between two readings, and each reading is checked for a possible leak. A bill concerns one meter and uses a SONEDE band and, when applicable, an ONAS band.'},
 quality_leaks:{title:'Quality & leaks',count:'3 classes + linked classes',nodes:{WaterZone:[20,30],WaterQualityTest:[390,30],AlertRule:[760,30],WaterMeter:[20,280],LeakIncident:[390,280],WaterPipe:[760,280]},explanation:'A laboratory test records measurements for a zone. A rule defines an alert threshold. An incident starts from a meter, a quality test, or both, and points to at most one suspected pipe or pump.'},
 sustainability:{title:'Savings & audits',count:'5 classes + their site',nodes:{ConservationTarget:[20,30],Site:[390,30],AuditReport:[760,30],SustainabilityProject:[20,280],MeasuredBenefit:[390,280],OptimizationRun:[760,280]},explanation:'A site sets reduction targets and has water-saving projects. Each project can be measured after the fact. An optimisation picks the best projects within a budget, and an audit freezes the indicators of a period in a PDF.'},
 core:{title:'User profiles',count:'3 classes',nodes:{UserProfile:[390,30],NetworkTechnician:[20,280],AuditManager:[760,280]},explanation:'Technicians and managers share common profile information and can each be linked to a login account. The technician maintains the network and investigates incidents.'},
 all:{title:'Full UML',count:'%d classes · %d links',explanation:'Generated from the Django models. Each line is a link (foreign key) between two classes, so link fields are not repeated inside the boxes. Zoom in to read, or choose one part for a simpler view.'}
}""" % (len(schema), n_links)
html = replace_between(html, "const configs=", ";\n", configs)
html = re.sub(r'<option value="all">Full UML · \d+ classes</option>', f'<option value="all">Full UML · {len(schema)} classes</option>', html)
html = html.replace("<span class=\"tab-number\">2</span>Class diagram", "<span class=\"tab-number\">2</span>Class diagram")
open(DOSSIER, "w", encoding="utf-8", newline="").write(html)
print(f"classes={len(schema)} links={n_links}")
for s in schema:
    print(f"  {s['module']:15} {s['name']:22} fields={len(s['fields']):2} methods={[m['name'] for m in s['methods']]}")
print(source.split("\n")[-50:][0:0] or "")
print("\n".join(l for l in source.split("\n") if "--" in l))
