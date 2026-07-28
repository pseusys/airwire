from secrets import token_bytes

import pytest

from sources.markov import END_TOKEN, MARKOV_ENG, MARKOV_RUS, MarkovEncoding, MarkovModelError

SAMPLES = [b"", b"\x00", b"\xff", b"hi", token_bytes(1), token_bytes(20), token_bytes(80)]


def _round_trip(encoding: MarkovEncoding, data: bytes) -> bytes:
    text = b"".join(encoding.encode_atoms(data))
    return encoding.decode(text, len(data))


@pytest.mark.parametrize("data", SAMPLES)
def test_english_round_trip(data: bytes) -> None:
    assert _round_trip(MARKOV_ENG, data) == data


@pytest.mark.parametrize("data", SAMPLES)
def test_russian_round_trip(data: bytes) -> None:
    assert _round_trip(MARKOV_RUS, data) == data


def test_round_trip_at_a_realistic_hyperslice_sized_sample() -> None:
    data = token_bytes(200)
    assert _round_trip(MARKOV_ENG, data) == data


def test_encode_is_deterministic() -> None:
    data = token_bytes(30)
    first = b"".join(MARKOV_ENG.encode_atoms(data))
    second = b"".join(MARKOV_ENG.encode_atoms(data))
    assert first == second


def test_different_inputs_produce_different_text() -> None:
    a = b"".join(MARKOV_ENG.encode_atoms(token_bytes(20)))
    b = b"".join(MARKOV_ENG.encode_atoms(token_bytes(20)))
    assert a != b


def test_output_looks_like_words_separated_by_spaces() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(30))).decode("utf-8")
    words = text.split()
    assert words, "Expected at least one word for non-trivial input!"
    assert all(word.strip() == word and word for word in words)


def test_output_contains_sentence_boundaries_for_longer_input() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(200))).decode("utf-8")
    assert END_TOKEN in text


def test_decode_rejects_word_not_valid_at_current_state() -> None:
    data = token_bytes(20)
    words = b"".join(MARKOV_ENG.encode_atoms(data)).decode("utf-8").split()
    words[0] = "supercalifragilisticexpialidocious"
    tampered = (" ".join(words) + " ").encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(tampered, len(data))


def test_decode_rejects_malformed_utf8() -> None:
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(b"\xff\xfe\x00", 3)


def test_decode_rejects_too_short_word_sequence() -> None:
    data = token_bytes(50)
    words = b"".join(MARKOV_ENG.encode_atoms(data)).decode("utf-8").split()
    truncated = (" ".join(words[: max(1, len(words) // 2)]) + " ").encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(truncated, len(data))


def test_tampering_a_still_valid_word_changes_the_recovered_bytes() -> None:
    data = token_bytes(20)
    words = b"".join(MARKOV_ENG.encode_atoms(data)).decode("utf-8").split()
    # Swap the first word for something valid at the begin state but (almost certainly) different.
    tampered = list(words)
    tampered[0] = "The" if tampered[0] != "The" else "A"
    original_text = (" ".join(words) + " ").encode("utf-8")
    tampered_text = (" ".join(tampered) + " ").encode("utf-8")
    original_result = MARKOV_ENG.decode(original_text, len(data))
    try:
        tampered_result = MARKOV_ENG.decode(tampered_text, len(data))
    except ValueError:
        return  # also an acceptable outcome: the swap desynchronized the walk entirely.
    assert tampered_result != original_result


def test_unknown_language_raises_markov_model_error() -> None:
    with pytest.raises(MarkovModelError):
        list(MarkovEncoding("xx").encode_atoms(b"data"))
