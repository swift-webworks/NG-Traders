"""
Import products from an export of the existing billing system.

    python manage.py import_products products.csv            # preview only (default, safe)
    python manage.py import_products products.csv --apply    # actually write to the database

Always take a database backup before using --apply on real data (see docs/DEPLOYMENT.md).
"""
from django.core.management.base import BaseCommand, CommandError

from catalogue import importer


class Command(BaseCommand):
    help = "Validate (and optionally apply) a CSV/XLSX product import."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--apply", action="store_true", help="Write changes (default is preview only).")

    def handle(self, *args, path, apply=False, **opts):
        try:
            with open(path, "rb") as fh:
                rows, columns = importer.read_table(fh, path)
        except (OSError, importer.ImportFileError) as exc:
            raise CommandError(str(exc))
        clean, summary = importer.build_preview(rows, columns)
        self.stdout.write(f"Rows: {summary['total']}  {summary['counts']}  price changes: {summary['price_changes']}")
        for r in clean:
            for e in r["errors"]:
                self.stdout.write(self.style.ERROR(f"  line {r['line']}: {e}"))
            for w in r["warnings"]:
                self.stdout.write(self.style.WARNING(f"  line {r['line']}: {w}"))
        if not apply:
            self.stdout.write("Preview only. Re-run with --apply to import the valid rows.")
            return
        report = importer.apply_rows(clean)
        self.stdout.write(self.style.SUCCESS(f"Done: {report}"))
