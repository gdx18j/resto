import ast
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


DEFAULT_PATHS = (
    "menu/translation_seed.py",
    "menu/translations.py",
    "data/caesar_and_company_menu_seed.json",
)


class DuplicateJsonKeyError(ValueError):
    pass


def duplicate_checking_object_pairs_hook(pairs):
    result = {}

    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")

        result[key] = value

    return result


class DuplicatePythonKeyVisitor(ast.NodeVisitor):
    def __init__(self, path):
        self.path = path
        self.errors = []

    def visit_Dict(self, node):
        seen = {}

        for key in node.keys:
            if not isinstance(key, ast.Constant):
                continue

            value = key.value

            if value in seen:
                self.errors.append(
                    f"{self.path}:{key.lineno}: duplicate Python dict key {value!r}; "
                    f"previous line {seen[value]}"
                )
            else:
                seen[value] = key.lineno

        self.generic_visit(node)


class Command(BaseCommand):
    help = "Validate translation source files for silent duplicate keys."

    def add_arguments(self, parser):
        parser.add_argument(
            "paths",
            nargs="*",
            help="Files to validate. Defaults to translation seed sources.",
        )

    def _validate_python(self, path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        visitor = DuplicatePythonKeyVisitor(path)
        visitor.visit(tree)
        return visitor.errors

    def _validate_json(self, path):
        try:
            json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=duplicate_checking_object_pairs_hook,
            )
        except DuplicateJsonKeyError as exc:
            return [f"{path}: {exc}"]

        return []

    def handle(self, *args, **options):
        paths = options["paths"] or DEFAULT_PATHS
        errors = []

        for raw_path in paths:
            path = Path(raw_path)

            if not path.is_absolute():
                path = settings.BASE_DIR / path

            if not path.exists():
                errors.append(f"{path}: file does not exist")
                continue

            if path.suffix == ".py":
                errors.extend(self._validate_python(path))
            elif path.suffix == ".json":
                errors.extend(self._validate_json(path))

        if errors:
            for error in errors:
                self.stderr.write(error)

            raise CommandError(f"Translation source validation failed: {len(errors)}")

        self.stdout.write(self.style.SUCCESS("Translation source files are valid."))
