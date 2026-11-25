"""Duplicate-take detector: synthetic repeated takes fail and independent statements pass."""

import pytest

import reel_plan as rp
from conftest import make_words

import takes

# Synthetic duplicate, restart and CTA recognition fixtures.
FIRST_TAKE = "Я три недели рисовал новую карту своего района. Я эти три недели рисовал зря."
POEMU = "Маршрут получился длинным, поэтому мы купили карту дорог. Поэтому оказалось, что бумага полезна."
CTA_THRICE = (
    "Пиши слово «выходные», и получишь маршрут прогулки. Пришли тебе гайд, пиши слово «выходные» в комментарии. "
    "Я пришлю тебе гайд про разные цветы на лугу."
)
CLEAN = "На рассвете автобус подошёл к мосту. Вдали поднялась стая птиц. На площадке мы разложили карту и нашли дорогу вдоль реки."


def words_of(text: str) -> list[rp.Word]:
    """Words 0.3 s long, 0.4 s apart (a sentence end adds a 0.3 s pause, as in speech)."""
    toks = text.split()
    gaps = {i: 0.3 for i, t in enumerate(toks) if t.rstrip("»\"')").endswith((".", "?", "!"))}
    return make_words(text, gap_after=gaps)


def kinds(text: str) -> set[str]:
    return {r.kind for r in takes.find_repeats(words_of(text))}


def test_same_thought_said_twice_is_a_near_duplicate_sentence() -> None:
    found = takes.find_repeats(words_of(FIRST_TAKE))
    assert [r.kind for r in found] == ["sentence"]
    assert "эти три недели рисовал зря" in found[0].second.lower()


def test_poetomu_restart_across_the_sentence_boundary_is_an_echo() -> None:
    found = takes.find_repeats(words_of(POEMU))
    assert any(r.kind == "echo" and "поэтому" in r.first.lower() for r in found)


def test_call_to_action_said_three_times_is_found_as_repeated_ngrams() -> None:
    found = takes.find_repeats(words_of(CTA_THRICE))
    texts = " | ".join(f"{r.first}~{r.second}" for r in found).lower()
    assert any(r.kind == "ngram" for r in found)
    assert "пиши слово выходные" in texts or "пиши слово «выходные»" in texts
    assert "пришли тебе гайд" in texts or "пришлю тебе гайд" in texts


def test_clean_final_text_has_no_repeats() -> None:
    assert takes.find_repeats(words_of(CLEAN)) == []


def test_fuzzy_match_survives_a_changed_ending_and_asr_slip() -> None:
    a = words_of("Пиши слово выходные в комментарии. Дальше идёт совсем другая мысль про гайд. Пишет слово выходные в комментарий.")
    assert takes.find_repeats(a), "«пиши… в комментарии» vs «пишет… в комментарий» is one thought said twice"


def test_far_apart_repeats_are_not_flagged() -> None:
    filler = " ".join("кошка собака дерево река гора облако трава камень ветер песок огонь вода земля небо звезда луна солнце море "
                      "лес поле дорога мост дом окно дверь стол стул ключ книга ручка чашка ложка тарелка нож вилка шкаф лампа "
                      "часы зеркало ковёр подушка одеяло кровать диван кресло полка картина ваза цветок птица рыба дракон ".split())
    text = f"Пиши слово выходные в комментарии. {filler}. Пиши слово выходные в комментарии."
    assert takes.find_repeats(words_of(text), window_s=15.0) == []


def test_stop_words_alone_do_not_count() -> None:
    assert takes.find_repeats(words_of("Я не знаю. Я не знаю.".replace("знаю", "и"))) == []


def test_allowlist_explains_a_deliberate_repeat() -> None:
    ws = words_of(FIRST_TAKE)
    found = takes.find_repeats(ws)
    assert found
    kept = takes.unexplained(found, allow=["эти три недели рисовал зря"])
    assert kept == []


def test_gate_message_names_both_takes_with_times() -> None:
    msg = takes.format_repeats(takes.find_repeats(words_of(FIRST_TAKE)))
    assert "[sentence]" in msg and "s)" in msg and "Я эти три недели" in msg


@pytest.mark.parametrize("text", [FIRST_TAKE, POEMU, CTA_THRICE])
def test_gate_fails_on_every_rejected_phrase(text: str) -> None:
    assert takes.check_takes(words_of(text)), "the gate must fail while an unexplained repeat remains"
