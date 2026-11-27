"""
Lanceur de tests : chaque exécution utilise un dossier de modèles d'IA vide et temporaire.

Sans cela, un modèle entraîné localement (media/ml/) changerait le résultat des tests.
Les tests qui ont besoin d'un modèle l'entraînent eux-mêmes dans ce dossier.
"""
import tempfile

from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class IsolatedMLTestRunner(DiscoverRunner):
    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._ml_dir = tempfile.TemporaryDirectory(prefix="aquamind-ml-tests-")
        self._ml_settings = override_settings(AQUAMIND_ML_DIR=self._ml_dir.name, AQUAMIND_FAILURE_MODEL_PATH="")
        self._ml_settings.enable()

    def teardown_test_environment(self, **kwargs):
        self._ml_settings.disable()
        self._ml_dir.cleanup()
        super().teardown_test_environment(**kwargs)
