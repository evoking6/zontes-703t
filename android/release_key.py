"""Persistent firmware release identity. Only the public key is an APK asset."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import re


def command(*args):
    result = subprocess.run(["openssl", *map(str, args)], check=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout


def public_key_id(public):
    description = command("rsa", "-pubin", "-in", public, "-text", "-noout").decode()
    bits = re.search(r"(?:Public-Key|RSA Public-Key): \((\d+) bit\)", description)
    if not bits or not 3072 <= int(bits[1]) <= 8192:
        raise RuntimeError("内置发布公钥必须为 RSA 3072–8192 位")
    der = command("pkey", "-pubin", "-in", public, "-outform", "DER")
    return hashlib.sha256(der).hexdigest()


def ensure_release_key(root):
    root = Path(root)
    private_dir = root / ".firmware-signing"
    private = private_dir / "release-private.pem"
    public = root / "assets/release-public.pem"
    if public.exists() and not private.exists():
        # A public-only source checkout can build the client, but cannot sign firmware.
        return {"public": public, "private": None, "key_id": public_key_id(public)}
    if not private.exists():
        private_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd, staged = tempfile.mkstemp(prefix=".new-release-key-", dir=private_dir)
        os.close(fd)
        try:
            command("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", staged)
            # Exclusive creation prevents overwriting an identity created by another build.
            os.link(staged, private)
        finally:
            os.unlink(staged)
    if private.is_symlink():
        raise RuntimeError("发布私钥不能为符号链接")
    private.chmod(0o600)
    derived = command("pkey", "-in", private, "-pubout")
    if public.exists():
        with tempfile.NamedTemporaryFile(suffix=".pem") as expected:
            expected.write(derived); expected.flush()
            if public_key_id(public) != public_key_id(expected.name):
                raise RuntimeError("内置公钥与发布私钥不匹配，已停止构建")
    else:
        public.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(public, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "wb") as out:
            out.write(derived); out.flush(); os.fsync(out.fileno())
    return {"public": public, "private": private, "key_id": public_key_id(public)}
