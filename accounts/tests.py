from django.contrib.auth.models import Permission, User
from django.test import Client, TestCase
from django.urls import reverse

# Every page that writes data in the modules, with the permission it requires.
# Permission checks run before the object lookup, so pk=1 does not need to exist.
WRITE_URLS = [
    ("consumption:meter_create", [], "consumption.add_watermeter"),
    ("consumption:reading_create", [], "consumption.add_meterreading"),
    ("consumption:meter_import", [1], "consumption.add_meterreading"),
    ("consumption:tariff_create", [], "consumption.add_tariffband"),
    ("consumption:bill_create", [], "consumption.add_waterbill"),
    ("quality_leaks:incident_create", [], "quality_leaks.add_leakincident"),
    ("quality_leaks:incident_resolve", [1], "quality_leaks.change_leakincident"),
    ("quality_leaks:test_create", [], "quality_leaks.add_waterqualitytest"),
    ("quality_leaks:rule_create", [], "quality_leaks.add_alertrule"),
    ("sustainability:target_create", [], "sustainability.add_conservationtarget"),
    ("sustainability:target_update", [1], "sustainability.change_conservationtarget"),
    ("sustainability:target_delete", [1], "sustainability.delete_conservationtarget"),
    ("sustainability:project_create", [], "sustainability.add_sustainabilityproject"),
    ("sustainability:project_update", [1], "sustainability.change_sustainabilityproject"),
    ("sustainability:project_delete", [1], "sustainability.delete_sustainabilityproject"),
    ("sustainability:benefit_create", [], "sustainability.add_measuredbenefit"),
    ("sustainability:benefit_update", [1], "sustainability.change_measuredbenefit"),
    ("sustainability:benefit_delete", [1], "sustainability.delete_measuredbenefit"),
    ("sustainability:optimize", [], "sustainability.add_optimizationrun"),
    ("sustainability:audit_report", [], "sustainability.add_auditreport"),
]
# Create forms that render with GET once the permission is granted.
GET_FORMS = [name for name, args, _ in WRITE_URLS if not args]


class ModulePermissionTests(TestCase):
    """A self-registered account must not be able to change data in any module."""

    def setUp(self):
        self.user = User.objects.create_user("reader", "reader@example.tn", "x-Pass-12345")

    def test_visitors_are_sent_to_login(self):
        for name, args, _ in WRITE_URLS:
            with self.subTest(url=name):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response.url)

    def test_read_only_account_gets_403_on_every_write_page(self):
        self.client.force_login(self.user)
        for name, args, _ in WRITE_URLS:
            for method in ("get", "post"):
                with self.subTest(url=name, method=method):
                    self.assertEqual(getattr(self.client, method)(reverse(name, args=args)).status_code, 403)

    def test_granted_permission_opens_the_form(self):
        for name, args, perm in WRITE_URLS:
            if name not in GET_FORMS:
                continue
            app_label, codename = perm.split(".")
            user = User.objects.create_user(f"u-{codename}", password="x-Pass-12345")
            user.user_permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))
            self.client.force_login(user)
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200)

    def test_read_only_account_can_still_view_modules(self):
        self.client.force_login(self.user)
        for name in ("consumption:dashboard", "consumption:meter_list", "quality_leaks:dashboard",
                     "quality_leaks:incident_list", "sustainability:dashboard", "sustainability:project_list",
                     "accounts:overview"):
            with self.subTest(url=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

VALID = {
    "username": "amira",
    "first_name": "Amira",
    "last_name": "Trabelsi",
    "email": "Amira.Trabelsi@Example.tn",
    "password1": "Eau-Potable-2026!",
    "password2": "Eau-Potable-2026!",
}


class SignUpTests(TestCase):
    def test_page_renders_for_visitors(self):
        response = self.client.get(reverse("signup"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Créer un compte")
        self.assertContains(response, reverse("login"))

    def test_signup_creates_a_read_only_account_and_logs_in(self):
        response = self.client.post(reverse("signup"), VALID, follow=True)
        self.assertRedirects(response, reverse("infrastructure:site_list"))
        self.assertContains(response, "Bienvenue Amira")
        user = User.objects.get(username="amira")
        self.assertEqual(user.email, "amira.trabelsi@example.tn")
        self.assertTrue(user.check_password("Eau-Potable-2026!"))
        self.assertNotEqual(user.password, "Eau-Potable-2026!")  # stored hashed
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertFalse(user.user_permissions.exists() or user.groups.exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        # Read-only: may view, may not create or administer.
        self.assertEqual(self.client.get(reverse("infrastructure:site_create")).status_code, 403)
        self.assertNotEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user("other", "amira.trabelsi@example.tn", "x-Pass-12345")
        response = self.client.post(reverse("signup"), VALID)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "déjà cette adresse")
        self.assertFalse(User.objects.filter(username="amira").exists())

    def test_duplicate_username_is_rejected(self):
        User.objects.create_user("amira", "someone@example.tn", "x-Pass-12345")
        self.assertEqual(self.client.post(reverse("signup"), VALID).status_code, 200)
        self.assertEqual(User.objects.filter(username="amira").count(), 1)

    def test_weak_or_mismatched_password_is_rejected(self):
        for password1, password2 in (("123", "123"), ("amira", "amira"), ("Eau-Potable-2026!", "different-2026!")):
            with self.subTest(password1=password1):
                data = dict(VALID, password1=password1, password2=password2)
                self.assertEqual(self.client.post(reverse("signup"), data).status_code, 200)
        self.assertFalse(User.objects.filter(username="amira").exists())

    def test_required_fields(self):
        response = self.client.post(reverse("signup"), {})
        for field in ("username", "first_name", "last_name", "email", "password1", "password2"):
            self.assertIn(field, response.context["form"].errors)

    def test_logged_in_user_is_redirected_away_from_signup(self):
        self.client.force_login(User.objects.create_user("x", password="x-Pass-12345"))
        self.assertRedirects(self.client.get(reverse("signup")), reverse("infrastructure:site_list"))

    def test_signup_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("signup"), VALID).status_code, 403)
        self.assertFalse(User.objects.exists())


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sami", "sami@example.tn", "x-Pass-12345")

    def test_login_page_links_to_signup(self):
        self.assertContains(self.client.get(reverse("login")), reverse("signup"))

    def test_login_then_logout(self):
        response = self.client.post(reverse("login"), {"username": "sami", "password": "x-Pass-12345"})
        self.assertRedirects(response, reverse("infrastructure:site_list"))
        self.assertEqual(self.client.get(reverse("infrastructure:site_list")).status_code, 200)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("infrastructure:site_list")).status_code, 302)

    def test_wrong_password_shows_an_error(self):
        response = self.client.post(reverse("login"), {"username": "sami", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Identifiant ou mot de passe incorrect")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logged_in_user_is_redirected_away_from_login(self):
        self.client.force_login(self.user)
        self.assertRedirects(self.client.get(reverse("login")), reverse("infrastructure:site_list"))

    def test_login_honours_next(self):
        target = reverse("infrastructure:work_list")
        response = self.client.post(reverse("login"), {"username": "sami", "password": "x-Pass-12345", "next": target})
        self.assertRedirects(response, target)

    def test_login_rejects_external_next(self):
        response = self.client.post(reverse("login"),
                                    {"username": "sami", "password": "x-Pass-12345", "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("infrastructure:site_list"))
