from secrets import token_bytes

import pytest

from sources.markov import BEGIN_TOKEN, END_TOKEN, MARKOV_ENG, MARKOV_RUS, MarkovEncoding, MarkovModelError, _finish_sentence

SAMPLES = [b"", b"\x00", b"\xff", b"hi", token_bytes(1), token_bytes(20), token_bytes(80)]
NONCE = token_bytes(24)  # now seeds real-content candidate order too, not just filler completion --
# see test_decode_with_wrong_nonce_does_not_recover_original_data.


def _round_trip(encoding: MarkovEncoding, data: bytes) -> bytes:
    text = b"".join(encoding.encode_atoms(data, NONCE))
    return encoding.decode(text, len(data), NONCE)


def _replace_first_word(text: str, replacement: str) -> str:
    lines = text.split("\n")
    words = lines[0].split()
    words[0] = replacement
    lines[0] = " ".join(words) + " "
    return "\n".join(lines)


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
    first = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    second = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    assert first == second


def test_different_inputs_produce_different_text() -> None:
    a = b"".join(MARKOV_ENG.encode_atoms(token_bytes(20), NONCE))
    b = b"".join(MARKOV_ENG.encode_atoms(token_bytes(20), NONCE))
    assert a != b


def test_output_looks_like_words_separated_by_spaces() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(30), NONCE)).decode("utf-8")
    words = text.split()
    assert words, "Expected at least one word for non-trivial input!"
    assert all(word.strip() == word and word for word in words)


def test_output_contains_newline_sentence_boundaries_for_longer_input() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(200), NONCE)).decode("utf-8")
    assert "\n" in text


def test_output_never_contains_the_literal_end_token() -> None:
    text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(200), NONCE)).decode("utf-8")
    assert END_TOKEN not in text


def test_decode_rejects_word_not_valid_at_current_state() -> None:
    data = token_bytes(20)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    tampered = _replace_first_word(text, "supercalifragilisticexpialidocious").encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(tampered, len(data), NONCE)


def test_decode_rejects_malformed_utf8() -> None:
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(b"\xff\xfe\x00", 3, NONCE)


def test_decode_rejects_too_short_word_sequence() -> None:
    data = token_bytes(50)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    truncated = text[: len(text) // 2].encode("utf-8")
    with pytest.raises(ValueError):
        MARKOV_ENG.decode(truncated, len(data), NONCE)


def test_tampering_a_still_valid_word_changes_the_recovered_bytes() -> None:
    data = token_bytes(20)
    text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE)).decode("utf-8")
    # Swap the first word for something valid at the begin state but (almost certainly) different.
    first_word = text.split("\n")[0].split()[0]
    replacement = "The" if first_word != "The" else "A"
    tampered_text = _replace_first_word(text, replacement)
    original_result = MARKOV_ENG.decode(text.encode("utf-8"), len(data), NONCE)
    try:
        tampered_result = MARKOV_ENG.decode(tampered_text.encode("utf-8"), len(data), NONCE)
    except ValueError:
        return  # also an acceptable outcome: the swap desynchronized the walk entirely.
    assert tampered_result != original_result


def test_unknown_language_raises_markov_model_error() -> None:
    with pytest.raises(MarkovModelError):
        list(MarkovEncoding("xx").encode_atoms(b"data", NONCE))


def test_markov_eng_and_rus_have_distinct_identifiers() -> None:
    assert MARKOV_ENG.identifier != MARKOV_RUS.identifier


def test_encoded_text_always_ends_with_a_completed_sentence() -> None:
    for size in (1, 5, 13, 37, 80, 199):
        text = b"".join(MARKOV_ENG.encode_atoms(token_bytes(size), NONCE)).decode("utf-8")
        assert text.endswith("\n"), f"Expected a completed final sentence for a {size}-byte payload!"


def test_filler_completion_is_deterministic() -> None:
    data = token_bytes(37)
    first = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    second = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
    assert first == second


def test_filler_completion_differs_across_nonces() -> None:
    # Checked across several sizes, not just one sample: whenever a payload happens to land
    # exactly on a sentence boundary, filler never triggers and the nonce genuinely has no effect
    # -- that's correct behavior, not a bug, but it means a single random sample is an unreliable
    # way to check this property.
    other_nonce = token_bytes(24)
    saw_difference = False
    for size in (1, 5, 13, 37, 80):
        data = token_bytes(size)
        a = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
        b = b"".join(MARKOV_ENG.encode_atoms(data, other_nonce))
        if a != b:
            saw_difference = True
    assert saw_difference


def test_decode_with_wrong_nonce_does_not_recover_original_data() -> None:
    # The seed now gates the ENTIRE walk, not just the filler tail -- decoding with the wrong
    # nonce should either recover corrupted bytes, or (when the wrong candidate order squeezes a
    # real word out of `candidate_ranges` entirely at a narrow bit budget -- see
    # sources/arithmetic.py's `candidate_ranges` docstring) raise ValueError outright. Both count
    # as "did not recover the original data"; checked across several sizes for the same reason the
    # filler-nonce test is: a single random sample is an unreliable way to check this property.
    other_nonce = token_bytes(24)
    saw_mismatch = False
    for size in (1, 5, 13, 37, 80, 199):
        data = token_bytes(size)
        text = b"".join(MARKOV_ENG.encode_atoms(data, NONCE))
        try:
            recovered = MARKOV_ENG.decode(text, len(data), other_nonce)
        except ValueError:
            saw_mismatch = True
            continue
        if recovered != data:
            saw_mismatch = True
    assert saw_mismatch


def test_round_trip_still_correct_when_filler_is_used() -> None:
    for size in (1, 5, 13, 37, 80, 199):
        data = token_bytes(size)
        assert _round_trip(MARKOV_ENG, data) == data


def test_finish_sentence_raises_when_no_path_to_end_exists() -> None:
    begin_state = (BEGIN_TOKEN, BEGIN_TOKEN)
    state_a = ("stuck", "here")
    state_b = ("here", "stuck")
    chain = {
        state_a: [("stuck", 1)],
        state_b: [("here", 1)],
    }
    with pytest.raises(MarkovModelError):
        list(_finish_sentence(chain, state_a, begin_state, b"\x00\x00\x00\x00"))
