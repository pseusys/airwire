#!/usr/bin/env python3
"""Verify the knowledge base and the repository's markdown house rules.

Checks, in order:

  1. links      every relative link in a tracked .md file resolves to a real path
  2. index      memory/README.md lists every memory doc, and only real ones
  3. keywords   memory/keywords.md routes to every memory doc, and only real ones
  4. header     every memory doc carries a *keywords:* line near its title
  5. style      the markdown conventions from memory/dos-and-donts.md

Structural problems (1-4) are errors and fail the run.
Style problems (5) are warnings unless --strict is passed.

Standard library only, by the rule in memory/automation-scripts.md, and written
to the Python rules in memory/coding-guidelines.md, which is what
`ruff check --config memory/scripts/ruff.toml memory/scripts/` enforces.

Run it from the repository root:

    python memory/scripts/verify_memory.py
    python memory/scripts/verify_memory.py --strict   # style problems fail too
    python memory/scripts/verify_memory.py --quiet    # errors only, no summary
"""

from __future__ import annotations

from argparse import ArgumentParser
from os import sep, walk
from os.path import abspath, dirname, exists, isdir, join, normpath, relpath
from re import IGNORECASE, MULTILINE, Match
from re import compile as re_compile
from sys import exit, stderr

# `compile` is aliased above because it shadows a builtin; `exit` is not,
# because sys.exit is the one every reader means by that name.

ENCODING = "utf-8"
NEWLINE = "\n"
POSIX_SEP = "/"
MARKDOWN_SUFFIX = ".md"

MEMORY_DIR = "memory"
INDEX_FILENAME = "README.md"
KEYWORDS_FILENAME = "keywords.md"
MEMORY_INDEX = f"{MEMORY_DIR}{POSIX_SEP}{INDEX_FILENAME}"
KEYWORD_INDEX = f"{MEMORY_DIR}{POSIX_SEP}{KEYWORDS_FILENAME}"

# Directories that hold markdown which is not part of the knowledge base proper.
# Archived changelogs are indexed as a group rather than file by file.
UNINDEXED_DIRS = {"changelog-archive", "scripts", "experiments"}
SKIP_TREE = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache"}

# A knowledge-base document sits directly inside memory/, so its path splits
# into exactly two segments; anything deeper lives in a subdirectory.
MEMORY_DOC_DEPTH = 2
# How far into a document to look for its *keywords:* line.
KEYWORDS_HEADER_LINES = 8
# Blank lines allowed between blocks.
MAX_CONSECUTIVE_BLANKS = 1

EXIT_OK = 0
EXIT_PROBLEMS = 1
EXIT_MISUSE = 2

LINK = re_compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+?)(?:#[^)]*)?\)")
EXTERNAL_SCHEME = re_compile(r"^[a-z][a-z0-9+.-]*:", IGNORECASE)
FENCE = re_compile(r"^\s*(?:```|~~~)")
TABLE_ROW = re_compile(r"^\s*\|")
SETEXT = re_compile(r"^\s*(=+|-{2,})\s*$")
INLINE_CODE = re_compile(r"`[^`]*`")
LEADING_EMPHASIS = re_compile(r"^\s*[*_]{1,2}")
# A bullet, or an ordinal such as "3.", "2b.", "I1.", "A4." opening a line.
ORDINAL = re_compile(r"^\s*(?:[-*+]|[A-Za-z]{0,2}\d+[a-z]?\.|\d+\.)\s+")
ABBREV = re_compile(r"(?:e\.g|i\.e|etc|vs|cf|approx|al|resp|Dr|Mr|Mrs|Ms|No|Fig|Sec|Ch|St|Inc|Ltd|Jr|Sr|a\.m|p\.m)\.$", IGNORECASE)
SENTENCE_BREAK = re_compile(r"""[.!?]["')\]]?\s+(?=["'(\[]?[A-Z])""")
KEYWORDS_LINE = re_compile(r"^\*keywords:\*\s+\S.*$", MULTILINE)


def blank(match: Match[str]) -> str:
    """Replace a match with spaces, so later offsets still line up with the source."""
    return " " * len(match.group(0))


class Report:
    """Collects the problems every check finds, and the checks that passed."""

    def __init__(self) -> None:
        """Start with nothing recorded."""
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.passed: list[str] = []

    def error(self, where: str, message: str) -> None:
        """Record a structural problem, which fails the run."""
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        """Record a style problem, which fails the run only under --strict."""
        self.warnings.append(f"{where}: {message}")

    def ok(self, message: str) -> None:
        """Record a check that passed, for the closing summary."""
        self.passed.append(message)


def markdown_files(root: str) -> list[str]:
    """Every markdown file in the tree, as paths relative to root, with / separators."""
    found: list[str] = []
    for dirpath, dirnames, filenames in walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_TREE]
        found.extend(relpath(join(dirpath, name), root).replace(sep, POSIX_SEP) for name in filenames if name.endswith(MARKDOWN_SUFFIX))
    return sorted(found)


def memory_docs(root: str) -> list[str]:
    """The knowledge-base documents that must appear in both indexes."""
    docs: list[str] = []
    for rel in markdown_files(root):
        parts = rel.split(POSIX_SEP)
        if parts[0] != MEMORY_DIR:
            continue
        if parts[-1] == INDEX_FILENAME and len(parts) == MEMORY_DOC_DEPTH:
            continue  # the index does not index itself
        if len(parts) > MEMORY_DOC_DEPTH and parts[1] in UNINDEXED_DIRS:
            continue
        docs.append(rel)
    return docs


def read(root: str, rel: str) -> str:
    """The full text of one file, addressed relative to the repository root."""
    with open(join(root, rel), encoding=ENCODING) as handle:
        return handle.read()


def check_links(root: str, report: Report) -> None:
    """Every relative link in a markdown file points at something that exists."""
    checked = 0
    for rel in markdown_files(root):
        text = read(root, rel)
        base = dirname(join(root, rel))
        for match in LINK.finditer(text):
            target = match.group(1)
            if EXTERNAL_SCHEME.match(target) or target.startswith("#"):
                continue  # a same-file anchor is not a file path -- nothing to resolve.
            checked += 1
            if not exists(normpath(join(base, target))):
                line = text.count(NEWLINE, 0, match.start()) + 1
                report.error(f"{rel}:{line}", f"link does not resolve: {target}")
    report.ok(f"{checked} internal links resolve")


def linked_docs(root: str, index_rel: str) -> set[str]:
    """The documents an index file links to, as repository-relative paths."""
    base = dirname(index_rel)
    linked: set[str] = set()
    for match in LINK.finditer(read(root, index_rel)):
        target = match.group(1)
        if EXTERNAL_SCHEME.match(target):
            continue
        linked.add(normpath(join(base, target)).replace(sep, POSIX_SEP))
    return linked


def check_index(root: str, index_rel: str, report: Report) -> None:
    """Every memory document is reachable from this index."""
    if not exists(join(root, index_rel)):
        report.error(index_rel, "index file is missing")
        return
    linked = linked_docs(root, index_rel)
    docs = memory_docs(root)
    missing = [doc for doc in docs if doc not in linked and doc != index_rel]
    for doc in missing:
        report.error(index_rel, f"does not route to {doc}")
    if not missing:
        report.ok(f"{index_rel} routes to all {len(docs)} memory docs")


def check_keywords_header(root: str, report: Report) -> None:
    """Every memory document carries a *keywords:* line near its title."""
    missing = 0
    for rel in memory_docs(root):
        head = NEWLINE.join(read(root, rel).splitlines()[:KEYWORDS_HEADER_LINES])
        if not KEYWORDS_LINE.search(head):
            missing += 1
            report.error(rel, f"no *keywords:* line in the first {KEYWORDS_HEADER_LINES} lines")
    if not missing:
        report.ok("every memory doc carries a *keywords:* line")


def sentence_breaks(line: str) -> list[int]:
    """Column offsets where a second sentence starts on the same line."""
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", ">")) or TABLE_ROW.match(line):
        return []
    # Blank out inline code, leading emphasis, and list or ordinal markers, so
    # that neither their punctuation nor "1." is read as the end of a sentence.
    body = INLINE_CODE.sub(blank, line)
    body = LEADING_EMPHASIS.sub(blank, body)
    body = ORDINAL.sub(blank, body)
    return [match.start() + 1 for match in SENTENCE_BREAK.finditer(body) if not ABBREV.search(body[: match.start() + 1].rstrip())]


def check_style(root: str, report: Report) -> None:
    """The markdown conventions that a config-driven linter cannot express."""
    for rel in markdown_files(root):
        text = read(root, rel)
        lines = text.splitlines()
        if text and not text.endswith(NEWLINE):
            report.warn(rel, "no newline at end of file")

        in_fence = False
        blanks = 0
        for number, line in enumerate(lines, start=1):
            where = f"{rel}:{number}"
            if FENCE.match(line):
                in_fence = not in_fence
                blanks = 0
                continue
            if in_fence:
                blanks = 0
                continue

            if line != line.rstrip():
                report.warn(where, "trailing whitespace")
            if "\t" in line:
                report.warn(where, "tab character; use spaces")

            if not line.strip():
                blanks += 1
                if blanks == MAX_CONSECUTIVE_BLANKS + 1:
                    report.warn(where, f"more than {MAX_CONSECUTIVE_BLANKS} consecutive blank line")
                continue
            blanks = 0

            if SETEXT.match(line) and number > 1 and lines[number - 2].strip():
                report.warn(where, "setext heading; use # instead")

            breaks = sentence_breaks(line)
            if breaks:
                report.warn(where, f"two sentences on one line (column {breaks[0]})")

    report.ok("markdown style checked")


def main() -> int:
    """Parse the arguments, run every check, print the report, and return an exit code."""
    parser = ArgumentParser(description="Verify the knowledge base and the markdown house rules.")
    parser.add_argument("--root", default=".", help="repository root (default: .)")
    parser.add_argument("--strict", action="store_true", help="style problems fail the run")
    parser.add_argument("--quiet", action="store_true", help="print problems only")
    args = parser.parse_args()

    root = abspath(args.root)
    if not isdir(join(root, MEMORY_DIR)):
        print(f"no {MEMORY_DIR}/ directory under {root}; run from the repository root", file=stderr)
        return EXIT_MISUSE

    report = Report()
    check_links(root, report)
    check_index(root, MEMORY_INDEX, report)
    check_index(root, KEYWORD_INDEX, report)
    check_keywords_header(root, report)
    check_style(root, report)

    for problem in report.errors:
        print(f"error  {problem}")
    for problem in report.warnings:
        print(f"warn   {problem}")

    if not args.quiet:
        for line in report.passed:
            print(f"ok     {line}")
        print(f"{NEWLINE}{len(report.errors)} errors, {len(report.warnings)} warnings")

    if report.errors or (args.strict and report.warnings):
        return EXIT_PROBLEMS
    return EXIT_OK


if __name__ == "__main__":
    exit(main())
