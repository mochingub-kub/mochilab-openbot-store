"""Rule-based fallback G2P for OOV words (Apache-2.0, see LICENSE.FastThaiG2P)."""

from __future__ import annotations

import re

from . import _th2ipa

_TLTK_PHON_RE = re.compile(r"<tr/>(.+?)\|<s/>")
_INITIALIZED = False

_TONE_MAP = {
    "0": "˧",
    "1": "˨˩",
    "2": "˥˩",
    "3": "˦˥",
    "4": "˩˩˦",
}

_CONSONANT_MAP = [
    ("kh", "kʰ"), ("ph", "pʰ"), ("th", "tʰ"), ("ch", "t͡ɕʰ"),
    ("c", "t͡ɕ"), ("N", "ŋ"), ("?", "ʔ"),
]

_VOWEL_MAP = [
    ("UUa", "ɯa̯"), ("Ua", "ɯa̯"), ("iia", "ia̯"), ("ia", "ia̯"),
    ("uua", "ua̯"), ("ua", "ua̯"),
    ("aa", "aː"), ("ii", "iː"), ("uu", "uː"), ("xx", "ɛː"),
    ("ee", "eː"), ("oo", "oː"), ("OO", "ɔː"), ("@@", "ɤː"), ("UU", "ɯː"),
    ("a", "a"), ("i", "i"), ("u", "u"), ("x", "ɛ"), ("e", "e"),
    ("o", "o"), ("O", "ɔ"), ("@", "ɤ"), ("U", "ɯ"),
]

_EN_WORD_RE = re.compile(r"^[A-Za-z']+$")


def _ensure_initialized() -> None:
    global _INITIALIZED
    if not _INITIALIZED:
        _th2ipa.initial()
        _INITIALIZED = True


def _tltk_syllable_to_ipa(syl: str) -> str:
    tone_digit = syl[-1] if syl and syl[-1] in "01234" else "0"
    if syl and syl[-1] in "01234":
        syl = syl[:-1]
    tone = _TONE_MAP[tone_digit]
    result = syl
    for old, new in _CONSONANT_MAP:
        result = result.replace(old, new)
    for old, new in _VOWEL_MAP:
        result = result.replace(old, new)
    if result and result[-1] in "ktp":
        vowel_chars = set("aeiouɔɛɯɤː̯")
        if any(c in vowel_chars for c in result[:-1]):
            result = result[:-1] + result[-1] + "̚"
    return result + tone


def fallback_g2p(word: str) -> str:
    if _EN_WORD_RE.match(word):
        from .en_g2p import en_g2p

        return en_g2p(word)
    _ensure_initialized()
    result = _th2ipa.g2p(word)
    match = _TLTK_PHON_RE.search(result)
    if not match:
        return word
    tltk_phon = match.group(1)
    syllables = []
    for part in re.split(r"[|~^]", tltk_phon):
        for sp in part.split("'"):
            sp = sp.strip()
            if sp:
                syllables.append(_tltk_syllable_to_ipa(sp))
    if syllables:
        return "/" + ".".join(syllables) + "/"
    return word
