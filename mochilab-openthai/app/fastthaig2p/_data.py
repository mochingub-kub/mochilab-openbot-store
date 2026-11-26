"""Locate FastThaiG2P runtime data in the verified TTS model cache directory.

## License

Copyright 2026 Charin Polpanumas and Amazon Web Services
Licensed under the Apache License, Version 2.0 (see LICENSE.FastThaiG2P).
"""

from __future__ import annotations

import os
from pathlib import Path

_DATA_ROOT: Path | None = None


def set_data_root(path: Path | str) -> None:
    global _DATA_ROOT
    _DATA_ROOT = Path(path)


def data_path(*parts: str) -> Path:
    if _DATA_ROOT is not None:
        return _DATA_ROOT.joinpath(*parts)
    env_root = os.environ.get("FASTTHAIG2P_DATA_DIR")
    if env_root:
        return Path(env_root).joinpath(*parts)
    return Path(__file__).parent.joinpath("data", *parts)
