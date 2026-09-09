"""
Download and locally cache the plain-text sentence corpora used to train the Markov-chain text
disguise model (see roadmap.md's steganographic-encoders bullet). Corpora come from Tatoeba's
per-language sentence exports (https://tatoeba.org/en/downloads, CC BY 2.0 FR / CC0 1.0): short,
crowd-written, conversational sentences -- a closer stylistic match for a disguised chat message
than a news or Wikipedia corpus would be.

Each corpus is downloaded once and cached on disk as a plain UTF-8 text file, one sentence per
line; subsequent calls for the same language reuse the cached file without touching the network
again. `fetch_corpus`'s `downloader` parameter is injectable so callers (tests, in particular)
don't need real network access to exercise the caching/extraction logic.
"""

from bz2 import BZ2File
from pathlib import Path
from shutil import copyfileobj
from typing import Callable, Dict, List
from urllib.request import urlopen

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "corpus"

CORPUS_URLS: Dict[str, str] = {
    "eng": "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2",
    "rus": "https://downloads.tatoeba.org/exports/per_language/rus/rus_sentences.tsv.bz2",
}

Downloader = Callable[[str, Path], None]


class CorpusError(Exception):
    pass


class UnsupportedLanguageError(CorpusError):
    pass


def _download(url: str, destination: Path) -> None:
    """Default downloader: stream `url` to `destination` over HTTP(S)."""

    with urlopen(url) as response, destination.open("wb") as out_file:
        copyfileobj(response, out_file)


def _extract_sentences(archive_path: Path) -> List[str]:
    """Pull the sentence text (3rd tab-separated column) out of a Tatoeba per-language .tsv.bz2 export."""

    sentences = []
    with BZ2File(archive_path) as archive:
        for raw_line in archive:
            fields = raw_line.decode("utf-8").rstrip("\n").split("\t", 2)
            if len(fields) == 3 and fields[2]:
                sentences.append(fields[2])
    return sentences


def fetch_corpus(language: str, cache_dir: Path = DEFAULT_CACHE_DIR, downloader: Downloader = _download, force: bool = False) -> Path:
    """
    Return the path to a cached, plain-text, one-sentence-per-line corpus for `language` (an
    ISO 639-3 code, e.g. "eng" or "rus"), downloading and extracting it first if it isn't cached
    yet, or if `force` is set.
    """

    if language not in CORPUS_URLS:
        raise UnsupportedLanguageError(f"No corpus source configured for language {language!r}; supported: {sorted(CORPUS_URLS)}!")

    cache_dir.mkdir(parents=True, exist_ok=True)
    text_path = cache_dir / f"{language}.txt"
    if text_path.exists() and not force:
        return text_path

    archive_path = cache_dir / f"{language}_sentences.tsv.bz2"
    if not archive_path.exists() or force:
        downloader(CORPUS_URLS[language], archive_path)

    sentences = _extract_sentences(archive_path)
    if not sentences:
        raise CorpusError(f"No sentences extracted from {archive_path}; corpus archive may be malformed!")

    text_path.write_text("\n".join(sentences) + "\n", encoding="utf-8")
    return text_path
