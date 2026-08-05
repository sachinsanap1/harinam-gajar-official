"""
Devanagari -> Roman transliteration, used only for generating URL slugs.

Why this exists: Vercel's Python runtime doesn't reliably pass non-ASCII
(Devanagari) characters through in the URL *path* down to Flask — English
slugs work fine, but a slug containing Marathi script 404s even though the
exact same text matches correctly in the database (confirmed via the
/cron/debug-reading-slug route while diagnosing this). Query-string
parameters aren't affected, only path segments, which is consistent with a
WSGI PATH_INFO encoding issue in that runtime layer specifically — not
something fixable from application code.

The fix: never put raw Devanagari into a URL. This is a simple phonetic
mapping — not a linguistically perfect transliteration scheme — good
enough to produce readable, unique, ASCII-safe slugs. The page's visible
title is completely unaffected; only the URL changes.
"""

_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ऋ": "ri", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "अं": "an", "अः": "ah",
}

_MATRAS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ं": "n", "ः": "h", "ँ": "n",
}

_CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
    "ळ": "l", "क्ष": "ksh", "ज्ञ": "gy",
}

_VIRAMA = "्"
_DIGITS = {"०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
           "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"}


def transliterate_devanagari(text):
    """Best-effort Devanagari -> Roman conversion for slug generation."""
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if ch in _DIGITS:
            out.append(_DIGITS[ch])
            i += 1
            continue

        if ch in _VOWELS:
            out.append(_VOWELS[ch])
            i += 1
            continue

        # Two-character consonant clusters (क्ष, ज्ञ) checked before single ones.
        two = text[i:i + 2]
        if two in _CONSONANTS:
            consonant = _CONSONANTS[two]
            i += 2
        elif ch in _CONSONANTS:
            consonant = _CONSONANTS[ch]
            i += 1
        else:
            # Not Devanagari (already ASCII/punctuation/etc.) — pass through.
            out.append(ch)
            i += 1
            continue

        out.append(consonant)

        # A consonant is followed by either: virama (no vowel sound, used
        # for conjuncts — swallow it and move on), a matra (vowel sign —
        # add its sound), or nothing (implicit "a" sound, Devanagari's
        # default short vowel baked into every consonant).
        if i < n and text[i] == _VIRAMA:
            i += 1
        elif i < n and text[i] in _MATRAS:
            out.append(_MATRAS[text[i]])
            i += 1
        else:
            out.append("a")

    return "".join(out)
