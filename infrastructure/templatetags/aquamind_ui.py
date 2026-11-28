"""Petits outils d'affichage communs aux 4 modules.

    {% load aquamind_ui %}
    {{ field|bs }}   champ de formulaire avec les classes Bootstrap (et « is-invalid » en cas d'erreur)
"""
from django import forms, template

register = template.Library()


@register.filter
def bs(field):
    widget = field.field.widget
    if isinstance(widget, (forms.CheckboxInput,)):
        css = "form-check-input"
    elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
        css = "form-select"
    else:
        css = "form-control"
    if field.errors:
        css += " is-invalid"
    existing = widget.attrs.get("class", "")
    return field.as_widget(attrs={"class": f"{existing} {css}".strip()})


@register.filter
def is_checkbox(field):
    return isinstance(field.field.widget, forms.CheckboxInput)
