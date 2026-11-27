from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

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

    def test_signup_creates_a_read_only_account_and_logs_in(self):
        response = self.client.post(reverse("signup"), VALID, follow=True)
        self.assertRedirects(response, reverse("infrastructure:site_list"))
        user = User.objects.get(username="amira")
        self.assertEqual(user.email, "amira.trabelsi@example.tn")
        self.assertTrue(user.check_password("Eau-Potable-2026!"))  # stored hashed, not in clear
        self.assertNotEqual(user.password, "Eau-Potable-2026!")
        self.assertFalse(user.is_staff or user.is_superuser)
        self.assertFalse(user.user_permissions.exists())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        # Read-only: may view, may not create.
        self.assertEqual(self.client.get(reverse("infrastructure:site_create")).status_code, 403)

    def test_duplicate_email_is_rejected_case_insensitively(self):
        User.objects.create_user("other", "amira.trabelsi@example.tn", "x-Pass-12345")
        response = self.client.post(reverse("signup"), VALID)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "déjà cette adresse")
        self.assertFalse(User.objects.filter(username="amira").exists())

    def test_weak_or_mismatched_password_is_rejected(self):
        for password1, password2 in (("123", "123"), ("Eau-Potable-2026!", "different-2026!")):
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

    def test_login_then_logout(self):
        response = self.client.post(reverse("login"), {"username": "sami", "password": "x-Pass-12345"})
        self.assertRedirects(response, reverse("infrastructure:site_list"))
        self.assertEqual(self.client.get(reverse("infrastructure:site_list")).status_code, 200)
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("infrastructure:site_list")).status_code, 302)

    def test_wrong_password_shows_an_error(self):
        response = self.client.post(reverse("login"), {"username": "sami", "password": "wrong"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_honours_next(self):
        target = reverse("infrastructure:work_list")
        response = self.client.post(reverse("login") + f"?next={target}",
                                    {"username": "sami", "password": "x-Pass-12345", "next": target})
        self.assertRedirects(response, target)

    def test_login_rejects_external_next(self):
        response = self.client.post(reverse("login"),
                                    {"username": "sami", "password": "x-Pass-12345", "next": "https://evil.example/"})
        self.assertRedirects(response, reverse("infrastructure:site_list"))

    def test_visitor_sees_login_and_signup_links(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, reverse("signup"))
