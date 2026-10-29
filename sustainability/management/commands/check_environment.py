"""Management command: verify the runtime foundation of Module 4.

Usage:
    python manage.py check_environment

Reports Django/Python versions, the database actually in use, whether the
connection really answers a query, pending model migrations, and which
optional data-science / PDF dependencies can be imported. Designed for
Phase 1 acceptance and for quickly diagnosing a broken demo laptop.
"""

from __future__ import annotations

import platform
import subprocess
import sys

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils.version import get_version


OPTIONAL_PACKAGES = (
    ('pandas', 'data processing'),
    ('numpy', 'numeric processing'),
    ('sklearn', 'K-Means facility clustering'),
    ('pulp', 'investment optimization'),
    ('xhtml2pdf', 'PDF audit reports'),
    ('weasyprint', 'PDF audit reports (preferred engine, needs GTK)'),
)


class Command(BaseCommand):
    help = 'Check the Django, database and dependency foundation for the sustainability module.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING('Runtime'))
        self.stdout.write(f'  Python          : {platform.python_version()}')
        self.stdout.write(f'  Django          : {get_version()}')
        self.stdout.write(f'  Platform        : {platform.system()} {platform.release()}')

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Database'))
        settings_dict = connection.settings_dict
        self.stdout.write(f'  Engine          : {settings_dict.get("ENGINE")}')
        self.stdout.write(f'  Vendor          : {connection.vendor}')
        self.stdout.write(f'  Name            : {settings_dict.get("NAME")}')
        self.stdout.write(f'  Host            : {settings_dict.get("HOST") or "(local file)"}')
        self.stdout.write(f'  Port            : {settings_dict.get("PORT") or "(n/a)"}')

        connected = self._check_connection()
        if connected:
            if connection.vendor == 'postgresql':
                with connection.cursor() as cursor:
                    cursor.execute('SHOW server_version;')
                    server_version = cursor.fetchone()[0]
                self.stdout.write(f'  Server version  : PostgreSQL {server_version}')
            self.stdout.write(self.style.SUCCESS('  Connection      : OK (SELECT 1 succeeded)'))
        else:
            self.stdout.write(self.style.ERROR('  Connection      : FAILED'))

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Migrations'))
        unapplied = self._unapplied_migrations()
        if not unapplied:
            self.stdout.write(self.style.SUCCESS('  All migrations applied'))
        else:
            for app_label, name in unapplied:
                self.stdout.write(self.style.WARNING(f'  Pending: {app_label}.{name}'))

        self.stdout.write('')
        self.stdout.write(self.style.MIGRATE_HEADING('Optional dependencies'))
        for module_name, purpose in OPTIONAL_PACKAGES:
            # Probing in a subprocess keeps noisy native-library banners
            # (WeasyPrint on Windows) out of the report and never poisons
            # this process with a half-initialised module.
            probe = subprocess.run(
                [sys.executable, '-c',
                 f'import {module_name} as m; print(getattr(m, "__version__", "?"))'],
                capture_output=True,
                text=True,
            )
            if probe.returncode == 0:
                version = (probe.stdout or '?').strip().splitlines()[-1] if probe.stdout.strip() else '?'
                self.stdout.write(f'  [ok] {module_name:<12} {purpose} ({version})')
            else:
                self.stdout.write(self.style.WARNING(
                    f'  [--] {module_name:<12} {purpose} (unavailable)'
                ))

        if not connected:
            self.stdout.write('')
            self.stdout.write(self.style.ERROR(
                'Database is unreachable. For PostgreSQL set DB_ENGINE=postgres and the '
                'POSTGRES_* variables in .env, or set DB_ENGINE=sqlite for the local fallback.'
            ))

    def _check_connection(self) -> bool:
        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return True
        except Exception as exc:  # noqa: BLE001 - surface the driver error message
            self.stdout.write(self.style.ERROR(f'  Error           : {exc}'))
            return False

    def _unapplied_migrations(self):
        try:
            executor = MigrationExecutor(connection)
            return sorted(executor.migration_plan(executor.loader.graph.leaf_nodes()))
        except Exception:  # noqa: BLE001 - DB may be down; already reported
            return []
