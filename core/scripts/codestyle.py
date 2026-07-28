from logging import getLogger
from pathlib import Path
from typing import List, Optional

from black import Mode, Report, WriteBack, reformat_one  # type: ignore
from flake8.api.legacy import get_style_guide
from mypy.api import run

# Root of the airwire core package.
CORE_ROOT = Path(__file__).parent.parent

# Maximum python source line length.
_MAX_LINE_LEN = 200

# All project files are checked, except generated protobuf bindings, dunder files, and anything
# under a dot-prefixed directory (.venv, .mypy_cache, .pytest_cache, ...).
_FILES = [str(f) for f in CORE_ROOT.glob("**/*.py") if not f.name.startswith("_") and "_pb2" not in f.name and not any(part.startswith(".") for part in f.relative_to(CORE_ROOT).parts)]

logger = getLogger(__name__)


def lint(files: Optional[List[str]] = None) -> int:
    """
    Run python code linting: `flake8`'s "error", "warning" and "fatal" checks, `black` in
    check-only mode, and `mypy --strict`.
    :param files: list of files to check, `None` for all project files.
    :return: exit code integer.
    """

    files = _FILES if files is None else files
    lint_result = 0

    selector = ["E", "W", "F"]
    ignore = ["E24", "W503", "E203"]  # E203 conflicts with `black`.
    report = get_style_guide(select=selector, ignore=ignore, max_line_length=_MAX_LINE_LEN).check_files(files)
    lint_result += sum(len(report.get_statistics(sel)) for sel in selector)

    lint_result += format(files, False)

    cache_dir = str(CORE_ROOT / ".mypy_cache")
    mypy_opts = ["--strict", "--ignore-missing-imports", "--cache-dir", cache_dir, "--explicit-package-bases"]
    out, err, code = run(mypy_opts + files)
    if code != 0:
        logger.error(f"{out}\n{err}")
    lint_result += code

    return lint_result


def format(files: Optional[List[str]] = None, modify: bool = True) -> int:
    """
    Format python code using `black`.
    :param files: list of files to check, `None` for all project files.
    :param modify: whether source files should be modified in place.
    :return: exit code integer.
    """

    files = _FILES if files is None else files
    write = WriteBack.YES if modify else WriteBack.CHECK
    mode = Mode(line_length=_MAX_LINE_LEN)
    report = Report(check=not modify, quiet=False)

    for path in files:
        reformat_one(Path(path), False, write, mode, report)

    return report.return_code
