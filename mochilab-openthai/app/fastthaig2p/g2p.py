"""FastThaiG2P grapheme-to-phoneme engine (Apache-2.0, see LICENSE.FastThaiG2P)."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any, Dict, Iterable, Optional, Union

from ._data import data_path
from .en_g2p import en_g2p
from .fallback import fallback_g2p
from .normalizer import normalize
from .tokenizer import Tokenizer

_EN_TOKEN_RE = re.compile(r"^[A-Za-z']+$")
_IPA_TONES = set("˧˨˩˥˩˦˥˩˩˦↓↑→↘↗")
_IPA_CHARS = set("ʔʰ̚ŋɕɔɛɯɤː̯")


def _is_ipa(pron: str) -> bool:
    pron = pron.strip()
    if not pron:
        return False
    if pron.startswith("/") and pron.endswith("/"):
        return True
    return any(c in _IPA_TONES or c in _IPA_CHARS for c in pron)


def _load_custom_dict(
    custom_dict: Optional[Union[Dict[str, str], str, Path, Iterable[Any]]]
) -> Dict[str, str]:
    if custom_dict is None:
        return {}
    if isinstance(custom_dict, dict):
        return {str(k).strip(): str(v).strip() for k, v in custom_dict.items() if str(k).strip()}
    if isinstance(custom_dict, (str, Path)):
        path = Path(custom_dict)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON custom dictionary must contain a key-value object.")
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(k).strip()}
    return {str(k).strip(): str(v).strip() for k, v in custom_dict if str(k).strip()}


class G2P:
    def __init__(
        self,
        dict_path: Path | str | None = None,
        ipa_path: Path | str | None = None,
        use_espeak: bool = False,
        custom_dict: Optional[Union[Dict[str, str], str, Path, Iterable[Any]]] = None,
    ):
        resolved_dict = Path(dict_path) if dict_path is not None else data_path("dict.txt")
        resolved_ipa = Path(ipa_path) if ipa_path is not None else data_path("ipa.json")
        self._tokenizer = Tokenizer(resolved_dict)
        self._ipa = json.loads(resolved_ipa.read_text(encoding="utf-8"))
        self.use_espeak = use_espeak
        self._custom_dict: Dict[str, str] = {}
        self._custom_ipa: Dict[str, str] = {}
        if custom_dict is not None:
            self.add_custom_dict(custom_dict)

    def add_custom_dict(
        self, custom_dict: Union[Dict[str, str], str, Path, Iterable[Any]]
    ) -> None:
        loaded = _load_custom_dict(custom_dict)
        for word, pron in loaded.items():
            self._custom_dict[word] = pron
            self._custom_ipa[word] = self._pronunciation_to_ipa(pron)
        self._tokenizer.add_words(loaded.keys())

    def _pronunciation_to_ipa(self, pron: str) -> str:
        pron = pron.strip()
        if not pron:
            return ""
        if _is_ipa(pron):
            return pron
        normalized = normalize(pron.replace("-", " "))
        tokens = self._tokenizer.tokenize(normalized)
        phonemes = []
        for token in tokens:
            if not token.strip():
                continue
            ipa = self._ipa.get(token)
            if ipa:
                phonemes.append(ipa)
            elif _EN_TOKEN_RE.match(token):
                phonemes.append(en_g2p(token, use_espeak=self.use_espeak))
            else:
                phonemes.append(fallback_g2p(token))
        return " ".join(phonemes)

    def convert(
        self,
        text: str,
        custom_dict: Optional[Union[Dict[str, str], str, Path, Iterable[Any]]] = None,
    ) -> str:
        normalized = normalize(text, custom_dict=self._custom_dict)
        tokens = self._tokenizer.tokenize(normalized)
        phonemes = []
        for token in tokens:
            if not token.strip():
                continue
            if token in self._custom_ipa:
                phonemes.append(self._custom_ipa[token])
            else:
                ipa = self._ipa.get(token)
                if ipa:
                    phonemes.append(ipa)
                elif _EN_TOKEN_RE.match(token):
                    phonemes.append(en_g2p(token, use_espeak=self.use_espeak))
                else:
                    phonemes.append(fallback_g2p(token))
        return " ".join(phonemes)
