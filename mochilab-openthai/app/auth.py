import os
from pathlib import Path
import secrets
import stat
import sys
import tempfile

KEY_PATH = Path("/data/credentials/api-key")


def load_key():
    try:
        descriptor = os.open(KEY_PATH, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        key = os.environ.get("APP_PASSWORD", "")
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise RuntimeError("Umbrel APP_PASSWORD must be a 64-character lowercase hexadecimal key") from None
        return key
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
            raise RuntimeError("The API key file must be a worker-owned regular file with mode 0600")
        key = source.read(258).removesuffix(b"\n")
    if not 32 <= len(key) <= 256 or any(byte < 33 or byte > 126 for byte in key):
        raise RuntimeError("The API key file must contain 32–256 printable ASCII characters without spaces")
    return key.decode("ascii")


def rotate_key():
    key = secrets.token_hex(32)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=KEY_PATH.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(key + "\n")
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(KEY_PATH)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return key


if __name__ == "__main__":
    if sys.argv[1:] != ["rotate"] or not sys.stdout.isatty():
        raise SystemExit("Run 'python /app/auth.py rotate' in a private interactive terminal.")
    print(rotate_key())
