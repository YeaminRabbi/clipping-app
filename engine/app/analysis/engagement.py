"""Transparent short-form text cues, not a model trained on engagement statistics.

Phrase cues currently cover English. Timing, silence and repetition work across languages.
"""

import re

TOKENS = re.compile(r"\w+(?:['’]\w+)*", re.UNICODE)
HOOKS = (
    "here is", "here's", "the biggest", "the best", "the worst", "the secret", "the truth",
    "nobody", "no one", "why", "how to", "the reason", "the key", "i learned", "mistake",
    "imagine", "what if", "you need to", "stop", "never", "most people", "you don't need",
    "you won't believe", "did you know", "instead of",
)
PAYOFFS = (
    "that's why", "that is why", "the lesson", "i learned", "the answer", "the result",
    "it turns out", "instead", "so you can", "which means", "in the end", "finally",
)
CONTRASTS = ("but", "however", "actually", "instead", "yet", "turns out", "wrong")
INTROS = ("welcome back", "welcome to", "thanks for watching", "thank you for watching", "before we start", "in this video")
PROMOS = ("subscribe to", "like and subscribe", "link in the description", "use my code", "our sponsor", "sponsored by")


def contains(text: str, phrases: tuple[str, ...]) -> bool:
    text = text.lower().replace("’", "'")
    return any(re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", text) for p in phrases)


def text_features(text: str, opening: str, ending: str) -> dict[str, float]:
    tokens = TOKENS.findall(text.lower())
    # Repeated four-word runs catch looping speech without penalizing normal repeated words.
    grams = [tuple(tokens[i : i + 4]) for i in range(max(0, len(tokens) - 3))]
    repetition = (1 - len(set(grams)) / len(grams)) if grams else 0.0
    return {
        "hook": float("?" in opening or contains(opening, HOOKS)),
        "payoff": float(contains(ending, PAYOFFS)),
        "contrast": float(contains(text, CONTRASTS)),
        "intro": float(contains(opening, INTROS)),
        "promo": float(contains(text, PROMOS)),
        "repetition": min(1.0, repetition * 2),
    }
