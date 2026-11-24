"""Unit tests for clip finding on synthetic transcripts and signals."""

import numpy as np

from app.analysis.candidates import (
    LEAD_IN_MS,
    TAIL_MS,
    Candidate,
    even_candidates,
    sentences,
    snap,
    talking_candidates,
)
from app.analysis.finder import FindSettings, find_clips, next_alternate
from app.analysis.scoring import Signals, auto_count, score_candidates, select
from app.analysis.engagement import text_features


def make_words(script: list[tuple[str, int]], word_ms: int = 300, gap_ms: int = 100) -> list[dict]:
    """Words from (sentence, pause-after-ms) pairs, spoken at a steady pace."""
    words, t = [], 1000
    for sentence, pause in script:
        for token in sentence.split():
            words.append({"start": t, "end": t + word_ms, "text": token})
            t += word_ms + gap_ms
        t += pause
    return words


SCRIPT = [
    ("Welcome back to the show everyone.", 800),
    ("And so we started with nothing at all.", 1500),
    ("Here is the biggest lesson about pricing.", 400),
    ("Never compete on price alone!", 400),
    ("Customers pay for value not the cheapest option.", 2000),
    ("So we moved offices and bought chairs.", 400),
    ("That was boring to be honest.", 1500),
]


def signals_for(words, duration_ms=40_000, cuts=None):
    loud = np.full(duration_ms // 100, -90.0)
    for w in words:
        loud[w["start"] // 100 : w["end"] // 100] = -20.0
    gaps = []
    for a, b in zip(words, words[1:]):
        if b["start"] - a["end"] >= 300:
            gaps.append((a["end"], b["start"]))
    return Signals(words=words, loudness=loud, cuts=cuts or [], silences=gaps)


def test_sentences_split_on_punctuation_and_long_pauses():
    words = make_words([("one two three", 1300), ("four five.", 100), ("six seven", 100)])
    texts = [s.text for s in sentences(words)]
    assert texts == ["one two three", "four five.", "six seven"]


def test_talking_candidates_are_whole_sentences_within_length():
    words = make_words(SCRIPT)
    sents = sentences(words)
    cands = talking_candidates(sents, 4000, 9000, 0, 60_000)
    assert cands
    starts = {s.start for s in sents}
    ends = {s.end for s in sents}
    for c in cands:
        assert c.start in starts and c.end in ends
        assert 4000 <= c.end - c.start <= 9000


def test_snap_never_cuts_into_words_and_prefers_nearby_scene_cuts():
    words = make_words(SCRIPT)
    sents = sentences(words)
    cand = talking_candidates(sents, 4000, 9000, 0, 60_000)[2]
    first, last = words[cand.first_word], words[cand.last_word]

    plain = snap(Candidate(**{**cand.__dict__}), words, [], [], 60_000)
    assert plain.start == max(first["start"] - LEAD_IN_MS, words[cand.first_word - 1]["end"] + 20)
    assert plain.end <= last["end"] + TAIL_MS

    # A cut 200 ms before the first word is used; one inside the first word is not.
    cut_ok = first["start"] - 200
    snapped = snap(Candidate(**{**cand.__dict__}), words, [cut_ok, first["start"] + 100], [], 60_000)
    assert snapped.start == cut_ok
    # Whatever happens, no word is cut: the previous word ends before the start, the next starts after the end.
    for c in (plain, snapped):
        if cand.first_word > 0:
            assert words[cand.first_word - 1]["end"] <= c.start <= first["start"]
        if cand.last_word + 1 < len(words):
            assert last["end"] <= c.end <= words[cand.last_word + 1]["start"]


def test_snap_with_touching_words_never_cuts_the_clips_own_words():
    # Whisper often gives back-to-back timings: "week." ends exactly when "It" starts.
    words = [
        {"start": 1000, "end": 1400, "text": "Left"},
        {"start": 1400, "end": 1880, "text": "week."},
        {"start": 1880, "end": 2300, "text": "It"},
    ]
    cand = Candidate(start=1000, end=1880, first_word=0, last_word=1)
    snapped = snap(cand, words, [], [], 10_000)
    assert snapped.end == 1880, "end sits on the boundary, not 20 ms inside 'week.'"
    cand = Candidate(start=1880, end=2300, first_word=2, last_word=2)
    assert snap(cand, words, [], [], 10_000).start == 1880


def test_keywords_hooks_and_weak_starts_affect_ranking():
    words = make_words(SCRIPT)
    sig = signals_for(words)
    cands = talking_candidates(sentences(words), 2000, 6000, 0, 60_000)
    score_candidates(cands, sig, "talking", ["pricing"])
    best = max(cands, key=lambda c: c.score)
    assert "pricing" in best.text.lower()
    assert "keyword: pricing" in best.reasons
    weak = next(c for c in cands if c.text.startswith("And so"))
    assert "starts mid-thought" in weak.reasons
    assert weak.score < best.score


def test_silence_lowers_score():
    sig = Signals(words=[], loudness=np.r_[np.full(100, -20.0), np.full(100, -90.0)], cuts=[], silences=[(10_000, 20_000)])
    loud, quiet = Candidate(0, 10_000), Candidate(10_000, 20_000)
    score_candidates([loud, quiet], sig, "action", [])
    assert loud.score > quiet.score


def test_select_respects_count_overlap_and_existing_clips():
    cands = [Candidate(0, 10_000, score=90), Candidate(5_000, 15_000, score=95), Candidate(20_000, 30_000, score=50),
             Candidate(40_000, 50_000, score=70)]  # fmt: skip
    chosen = select(cands, 2, taken=[(42_000, 44_000)])
    assert [(c.start, c.end) for c in chosen] == [(5_000, 15_000), (20_000, 30_000)]


def test_auto_count_and_even_split():
    assert auto_count(10 * 60_000, 30_000) == 5
    assert auto_count(10_000, 30_000) == 1
    assert auto_count(10 * 3600_000, 30_000) == 30
    parts = even_candidates(4, 10_000, 20_000, 0, 60_000)
    assert len(parts) == 4 and all(p.duration == 15_000 for p in parts)
    assert all(a.end <= b.start for a, b in zip(parts, parts[1:]))


def test_find_clips_falls_back_without_speech():
    sig = Signals(words=[], loudness=np.full(600, -25.0), cuts=[10_000, 30_000], silences=[])
    settings = FindSettings(mode="talking", count=2, min_ms=8_000, max_ms=12_000, lo=0, hi=60_000)
    result = find_clips(settings, sig, 60_000, [])
    assert result.mode_used == "action" and len(result.chosen) == 2
    assert "No speech" in result.notes[0]
    # Windows starting near a scene cut snap onto it.
    assert any(c.start in (10_000, 30_000) for c in result.chosen)


def test_find_clips_talking_end_to_end_and_titles():
    words = make_words(SCRIPT)
    settings = FindSettings(mode="talking", count=2, min_ms=3_000, max_ms=8_000, lo=0, hi=40_000, keywords=["pricing"])
    result = find_clips(settings, signals_for(words), 40_000, [])
    assert len(result.chosen) == 2
    assert result.chosen[0].start < result.chosen[1].start
    assert any("pricing" in c.text.lower() for c in result.chosen)
    assert all(c.title and not c.title.endswith(".") for c in result.chosen)
    assert all(p.title for p in result.pool)


def test_next_alternate_skips_shown_and_overlapping():
    pool = [{"start": 0, "end": 10}, {"start": 5, "end": 15}, {"start": 20, "end": 30}, {"start": 40, "end": 50}]
    assert next_alternate(pool, taken=[(25, 26)], skip={(0, 10)}) == {"start": 5, "end": 15}
    assert next_alternate(pool, taken=[(0, 16)], skip=set()) == {"start": 20, "end": 30}
    assert next_alternate(pool, taken=[(0, 60)], skip=set()) is None


def speech_candidate(text, lead_ms=150):
    words = make_words([(text, 0)])
    cand = Candidate(words[0]["start"] - lead_ms, words[-1]["end"] + 300,
                     text=text, sentences=[text], first_word=0, last_word=len(words) - 1)
    return cand, signals_for(words)


def speech_score(text, lead_ms=150):
    cand, sig = speech_candidate(text, lead_ms)
    score_candidates([cand], sig, "talking", [])
    return cand


def test_immediate_hook_beats_the_same_hook_delayed_by_an_intro():
    immediate = speech_score("The biggest mistake is chasing every customer. Instead focus on the customers who need your product.")
    delayed = speech_score("Welcome back to the show everyone we have a lot to discuss today. The biggest mistake is chasing every customer.")
    assert immediate.score > delayed.score
    assert "strong opening line" in immediate.reasons
    assert "intro before the main point" in delayed.reasons
    assert "strong opening line" not in delayed.reasons


def test_takeaway_and_contrast_outrank_generic_complete_sentences():
    story = speech_score("Most people chase every customer. But that fails. The lesson is focus on the people who need your product.")
    generic = speech_score("We spoke about the customers yesterday. We discussed several different topics and then we went back to our desks.")
    assert story.score > generic.score
    assert "conclusion or takeaway cue" in story.reasons


def test_repeated_speech_and_promotions_reduce_ranking():
    repeated = speech_score("The secret is focus. The secret is focus. The secret is focus. The secret is focus.")
    varied = speech_score("The secret is focus. Start with one customer. Learn what they need. The lesson is solve one problem well.")
    assert varied.score > repeated.score
    assert "repeated speech" in repeated.reasons
    base = "The biggest mistake is ignoring customers. The lesson is ask what they need."
    assert speech_score(base).score > speech_score(base + " Use my code and subscribe to our channel.").score


def test_hook_phrases_match_words_not_substrings():
    assert text_features("A stopwatch is useful.", "A stopwatch is useful.", "")['hook'] == 0
    assert text_features("Why does this fail?", "Why does this fail?", "")['hook'] == 1


def test_exclamation_marks_do_not_manufacture_an_emotion_score():
    assert speech_score("We moved the chairs into the room.").score == speech_score("We moved the chairs into the room!!!").score


def test_dead_air_at_the_opening_reduces_ranking():
    text = "The biggest mistake is ignoring customers. The lesson is ask what they need."
    clean = speech_score(text)
    slow = speech_score(text, lead_ms=1000)
    assert clean.score > slow.score
    assert "slow opening" in slow.reasons


def test_flat_audio_does_not_get_loud_moment_bonus():
    sig = Signals(words=[], loudness=np.full(100, -20.0), cuts=[], silences=[])
    cand = Candidate(0, 10_000)
    score_candidates([cand], sig, "action", [])
    assert "loud moments" not in cand.reasons
    assert cand.score < 10
