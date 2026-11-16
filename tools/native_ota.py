#!/usr/bin/env python3
"""Sign a stock-compatible TAR for the simplified Android TCP client. Offline only.

Does not invent an installer or add rollback to an unprotected input. The input's
panel entrypoints must already invoke the declared test/rollback transaction.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

MODEL = "JC_703T25"
META, SIG = "ota703t/manifest.json", "ota703t/manifest.sig"
MAX_BYTES = 520 * 1024 * 1024


def need(ok, message):
    if not ok:
        raise ValueError(message)


def openssl(*args):
    return subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=60).stdout


def path_ok(name):
    need(0 < len(name) <= 200 and all(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", part) for part in name.split("/")), "Unsafe TAR path: " + name)


def add(tar, name, data, mode=0o644):
    item = tarfile.TarInfo(name)
    item.size, item.mode, item.uid, item.gid, item.mtime = len(data), mode, 0, 0, 0
    tar.addfile(item, io.BytesIO(data))


def build(source, output, private_key, kind, release, base_version="", test_script="", rollback_script=""):
    source, output = Path(source), Path(output)
    need(source.is_file() and source.stat().st_size <= MAX_BYTES, "Input missing or too large")
    need(not output.exists() and output.suffix == ".tar", "Output must be a new .tar")
    need(kind in ("full", "incremental") and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}", release), "Invalid kind/release")
    need(not base_version or re.fullmatch(r"JC_703T25_V[0-9.]{1,30}", base_version), "Invalid base version")
    need(kind != "incremental" or bool(base_version), "Incremental requires exact reported base version")
    if kind == "full":
        need(not test_script and not rollback_script, "Full package does not use incremental script fields")
    der = openssl("pkey", "-in", private_key, "-pubout", "-outform", "DER")
    key_id = hashlib.sha256(der).hexdigest()
    rows = []
    with tarfile.open(source, "r:") as src:
        members = {}
        for item in src:
            name = item.name.rstrip("/") if item.isdir() else item.name
            path_ok(name)
            need(name not in members and len(members) < 4096, "Duplicate/excessive members")
            need(not item.pax_headers and not item.sparse and (item.isfile() or item.isdir()), "Links/extensions/special files forbidden")
            need(name not in (META, SIG), "Input is already signed; use the original input")
            members[name] = item
        for name in members:
            parts = name.split("/")
            for at in range(1, len(parts)):
                parent = members.get("/".join(parts[:at]))
                need(parent is None or parent.isdir(), "File/directory conflict")
        files = {n: m for n, m in members.items() if m.isfile()}
        need(bool(files), "Empty firmware")
        if kind == "incremental":
            need(test_script != rollback_script, "Test and rollback scripts must differ")
            for name in (test_script, rollback_script):
                need(name in files and name.endswith(".sh") and files[name].size > 0 and files[name].mode & 0o111, "Executable test/rollback scripts required")
            need({"updateFile_GT.sh", "updateFile_HW.sh"} <= files.keys(), "Both panel entrypoints required")
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(output, "x:", format=tarfile.USTAR_FORMAT) as dst:
                for name, item in files.items():
                    mode = 0o755 if item.mode & 0o111 else 0o644
                    data = src.extractfile(item)
                    digest = hashlib.sha256()
                    while chunk := data.read(65536):
                        digest.update(chunk)
                    rows.append({"path": name, "size": item.size, "mode": mode, "sha256": digest.hexdigest()})
                    header = tarfile.TarInfo(name)
                    header.size, header.mode = item.size, mode
                    dst.addfile(header, src.extractfile(item))
                manifest = {"schema": "703t-native-ota-v1", "model": MODEL, "kind": kind, "release": release,
                            "base_version": base_version, "key_id": key_id, "files": rows,
                            "test_script": test_script, "rollback_script": rollback_script}
                raw = json.dumps(manifest, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
                with tempfile.TemporaryDirectory(prefix="703t-native-sign-") as tmp:
                    path = Path(tmp, "manifest.json")
                    path.write_bytes(raw)
                    signature = openssl("dgst", "-sha256", "-sign", private_key, path)
                add(dst, META, raw)
                add(dst, SIG, signature)
            need(output.stat().st_size <= MAX_BYTES, "Output too large")
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    with output.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {"path": str(output), "kind": kind, "release": release, "base_version": base_version,
              "bytes": output.stat().st_size, "sha256": digest, "files": len(rows)}
    output.with_suffix(".tar.sha256").write_text(result["sha256"] + "  " + output.name + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--private-key", required=True, type=Path)
    p.add_argument("--kind", choices=("full", "incremental"), required=True)
    p.add_argument("--release", required=True)
    p.add_argument("--base-version", default="")
    p.add_argument("--test-script", default="")
    p.add_argument("--rollback-script", default="")
    a = p.parse_args()
    print(json.dumps(build(a.input, a.output, a.private_key, a.kind, a.release, a.base_version, a.test_script, a.rollback_script), ensure_ascii=False))


if __name__ == "__main__":
    main()
