"""Vendored FastThaiG2P (Apache-2.0, see LICENSE.FastThaiG2P)."""

from __future__ import annotations

from ._data import data_path, set_data_root
from .en_g2p import EnglishG2P, en_g2p, en_ipa_to_thai_ipa, en_to_ipa
from .g2p import G2P
from .kokoro import ipa_to_kokoro
from .normalizer import normalize
from .tokenizer import Tokenizer

__all__ = [
    "G2P",
    "EnglishG2P",
    "Tokenizer",
    "data_path",
    "en_g2p",
    "en_ipa_to_thai_ipa",
    "en_to_ipa",
    "ipa_to_kokoro",
    "normalize",
    "set_data_root",
]
