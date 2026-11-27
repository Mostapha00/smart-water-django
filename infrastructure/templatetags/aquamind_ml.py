"""
Badge qui indique d'où vient une prédiction : modèle d'IA entraîné, solveur, ou simple règle.

    {% load aquamind_ml %}
    {% ml_badge eq.model_version %}

Vert « Modèle IA » : Random Forest, LightGBM, Isolation Forest ou solveur PuLP.
Orange « Modèle IA · démo » : Random Forest entraîné sur trop peu de pannes pour être fiable.
Gris « Règle » : calcul simple (moyenne, seuils, tri glouton), pas un modèle d'IA.
"""
from django import template
from django.utils.html import format_html

from infrastructure.services.artifacts import is_ml_version

register = template.Library()


def _is_demo(version):
    if not version.startswith("random-forest"):
        return False
    from infrastructure.services.risk import load_model

    artifact = load_model()
    return bool(artifact and artifact.get("version") == version and artifact.get("metrics", {}).get("demo"))


@register.simple_tag
def ml_badge(version):
    if not version:
        return format_html('<span class="badge text-bg-light border" title="Pas encore calculé">non calculé</span>')
    if is_ml_version(version):
        if _is_demo(version):
            return format_html(
                '<span class="badge text-bg-warning" title="Modèle entraîné sur trop peu de pannes enregistrées : '
                'démonstration de la méthode, prédiction non fiable. ({})">Modèle IA · démo</span>', version)
        return format_html('<span class="badge text-bg-success" title="Résultat d\'un modèle d\'IA entraîné ou d\'un solveur ({})">'
                           'Modèle IA</span>', version)
    return format_html('<span class="badge text-bg-secondary" title="Règle simple, pas un modèle d\'IA ({})">Règle</span>', version)
