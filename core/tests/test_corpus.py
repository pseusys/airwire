from bz2 import compress
from pathlib import Path
from typing import List, Tuple

import pytest

from sources.corpus import CorpusError, Downloader, UnsupportedLanguageError, fetch_corpus

SAMPLE_ROWS = [
    ("1", "eng", "Hello there."),
    ("2", "eng", "How are you?"),
    ("3", "eng", "I am fine, thanks."),
]


def _fake_downloader(rows: List[Tuple[str, str, str]]) -> Downloader:
    calls = []

    def downloader(url: str, destination: Path) -> None:
        calls.append(url)
        content = "\n".join("\t".join(row) for row in rows).encode("utf-8")
        destination.write_bytes(compress(content))

    downloader.calls = calls  # type: ignore[attr-defined]
    return downloader


def test_fetch_corpus_extracts_sentence_column_only(tmp_path: Path) -> None:
    downloader = _fake_downloader(SAMPLE_ROWS)
    text_path = fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
    lines = text_path.read_text(encoding="utf-8").splitlines()
    assert lines == ["Hello there.", "How are you?", "I am fine, thanks."]


def test_fetch_corpus_uses_cache_on_second_call(tmp_path: Path) -> None:
    downloader = _fake_downloader(SAMPLE_ROWS)
    first_path = fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
    second_path = fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
    assert first_path == second_path
    assert len(downloader.calls) == 1, "Downloader should not be invoked again once the corpus is cached!"  # type: ignore[attr-defined]


def test_fetch_corpus_force_redownloads(tmp_path: Path) -> None:
    downloader = _fake_downloader(SAMPLE_ROWS)
    fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
    fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader, force=True)
    assert len(downloader.calls) == 2  # type: ignore[attr-defined]


def test_fetch_corpus_skips_malformed_and_empty_rows(tmp_path: Path) -> None:
    rows = [("1", "eng", "Valid sentence."), ("2", "eng", ""), ("3", "eng")]
    downloader = _fake_downloader(rows)  # type: ignore[arg-type]
    text_path = fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
    assert text_path.read_text(encoding="utf-8").splitlines() == ["Valid sentence."]


def test_fetch_corpus_rejects_unsupported_language(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedLanguageError):
        fetch_corpus("xyz", cache_dir=tmp_path, downloader=_fake_downloader(SAMPLE_ROWS))


def test_fetch_corpus_raises_on_empty_archive(tmp_path: Path) -> None:
    downloader = _fake_downloader([])
    with pytest.raises(CorpusError):
        fetch_corpus("eng", cache_dir=tmp_path, downloader=downloader)
