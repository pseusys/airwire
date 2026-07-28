from logging import getLogger
from pathlib import Path

logger = getLogger(__name__)

_CORE_ROOT = Path(__file__).parent.parent
_DATA_DIR = _CORE_ROOT / "sources" / "data"

# Kept modest on purpose: JSON size scales roughly linearly with sentence count (~3.5MB/20k
# sentences for English, ~7.5MB/20k for Russian, measured against Tatoeba's per-language export),
# and both encoder and decoder need to ship an identical copy of this frozen model.
DEFAULT_MAX_SENTENCES = 20_000
STATE_SIZE = 2


def train(max_sentences: int = DEFAULT_MAX_SENTENCES) -> int:
    """
    Train a frozen Markov-chain text model per supported language from the cached Tatoeba
    corpora (see `sources/corpus.py`; downloads them on first run if not cached yet), and write
    each one to `sources/data/markov_<language>.json`. Requires the `devel` extra (`markovify`).
    :return: exit code integer.
    """

    import markovify

    from sources.corpus import CORPUS_URLS, fetch_corpus

    _DATA_DIR.mkdir(parents=True, exist_ok=True)

    for language in CORPUS_URLS:
        corpus_path = fetch_corpus(language)
        lines = corpus_path.read_text(encoding="utf-8").splitlines()[:max_sentences]
        model = markovify.NewlineText("\n".join(lines), state_size=STATE_SIZE, retain_original=False)

        output_path = _DATA_DIR / f"markov_{language}.json"
        output_path.write_text(model.to_json(), encoding="utf-8")
        logger.info(
            "Trained %s model: %d sentences -> %s (%.1f KB)",
            language,
            len(lines),
            output_path,
            output_path.stat().st_size / 1024,
        )

    return 0
