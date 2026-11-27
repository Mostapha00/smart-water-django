from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    """Création de compte : identifiant, nom, e-mail unique et mot de passe validé.

    Le compte créé n'a AUCUNE permission : un administrateur attribue ensuite les droits
    (Administration › Utilisateurs ou Groupes). Sinon, n'importe qui pourrait modifier les données.
    """

    first_name = forms.CharField(label="Prénom", max_length=150)
    last_name = forms.CharField(label="Nom", max_length=150)
    email = forms.EmailField(label="E-mail")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        autocomplete = {"username": "username", "first_name": "given-name", "last_name": "family-name",
                        "email": "email", "password1": "new-password", "password2": "new-password"}
        for name, field in self.fields.items():
            field.widget.attrs.update({"class": "form-control", "autocomplete": autocomplete.get(name, "off")})
        self.fields["username"].help_text = "Lettres, chiffres et @ . + - _ uniquement."

    def clean_email(self):
        email = User.objects.normalize_email(self.cleaned_data["email"]).lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Un compte utilise déjà cette adresse e-mail.")
        return email
