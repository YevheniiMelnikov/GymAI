import os
import sys
from pathlib import Path
from typing import Final

ROOT_DIR: Path = Path(__file__).resolve().parent.parent
python_path: list[str] = sys.path
if str(ROOT_DIR) not in python_path:
    python_path.append(str(ROOT_DIR))

SETTINGS_MODULE: Final[str] = "config.settings"


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", SETTINGS_MODULE)
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
