"""FastThaiG2P tokenizer wrapper (Apache-2.0, see LICENSE.FastThaiG2P)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, Union

from pythainlp.tokenize import Tokenizer as _PyThaiTokenizer

from ._data import data_path


class Tokenizer:
    def __init__(
        self,
        dict_path: Path | str | None = None,
        custom_dict: Optional[Union[Iterable[str], dict, str, Path]] = None,
    ):
        resolved = Path(dict_path) if dict_path is not None else data_path("dict.txt")
        words = set(resolved.read_text(encoding="utf-8").splitlines())
        words.discard("")
        self._base_dict = words
        self._custom_words: set[str] = set()
        self._dict = set(self._base_dict)
        if custom_dict:
            self.add_words(custom_dict)
        else:
            self._engine = _PyThaiTokenizer(custom_dict=self._dict, engine="newmm")

    @property
    def vocab(self) -> set[str]:
        return self._dict

    def add_words(self, words: Union[Iterable[str], dict, str, Path]) -> None:
        if isinstance(words, (str, Path)):
            path = Path(words)
            if path.exists():
                if path.suffix.lower() == ".json":
                    loaded = json.loads(path.read_text(encoding="utf-8"))
                    words = loaded.keys() if isinstance(loaded, dict) else loaded
                else:
                    words = [
                        line.split("\t")[0].split(",")[0].split(":")[0].strip()
                        for line in path.read_text(encoding="utf-8").splitlines()
                        if line.strip() and not line.strip().startswith("#")
                    ]
            else:
                words = [str(words)]
        elif isinstance(words, dict):
            words = words.keys()
        for word in words:
            cleaned = str(word).strip()
            if cleaned:
                self._custom_words.add(cleaned)
        self._dict = self._base_dict | self._custom_words
        self._engine = _PyThaiTokenizer(custom_dict=self._dict, engine="newmm")

    def tokenize(self, text: str) -> list[str]:
        return self._engine.word_tokenize(text)
