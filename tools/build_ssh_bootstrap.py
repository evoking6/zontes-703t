#!/usr/bin/env python3
"""Build a native-OTA SSH bootstrap with a terminal Linux restart entrypoint.

Preserves the tested SSH component byte-for-byte and only changes the three
factory entrypoints. Does not connect to any device or flash firmware.
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
import native_ota

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "dist/JC_703T25_SSH_0.1.2_CANDIDATE.tar"
SOURCE_SHA = "1a63073fb7f10a6ada030f348866f875b2ce90895f31041dfbab26fde236550f"
OUTPUT = ROOT / "dist/JC_703T25_SSH_NATIVE_0.1.3_CANDIDATE.tar"
ENTRYPOINTS = {"updateFile.sh", "updateFile_GT.sh", "updateFile_HW.sh"}


def build(source, expected_sha, output, release, public_key, private_key):
    source, output = Path(source), Path(output)
    native_ota.need(source.is_file() and source.stat().st_size <= native_ota.MAX_BYTES, "Input missing or too large")
    native_ota.need(hashlib.sha256(source.read_bytes()).hexdigest() == expected_sha, "Reviewed source changed")
    subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public_key),
                    "-signature", str(source) + ".sig", str(source)], check=True, capture_output=True)
    entries = {}
    with tarfile.open(source, "r:") as archive:
        for member in archive:
            native_ota.path_ok(member.name)
            native_ota.need(member.name not in entries and len(entries) < 4096, "Duplicate/excessive members")
            native_ota.need(member.isfile() and not member.pax_headers and not member.sparse, "Regular component files only")
            native_ota.need(member.name in ENTRYPOINTS or member.name.startswith("ssh703t/"), "Unexpected component path")
            entries[member.name] = (archive.extractfile(member).read(), member.mode)
    native_ota.need(ENTRYPOINTS <= entries.keys() and "ssh703t/install.sh" in entries, "Missing component installer/entrypoints")
    installer = entries["ssh703t/install.sh"][0].decode()
    component = re.search(r"^RELEASE=([A-Za-z0-9_.-]+)$", installer, re.M)
    counter = re.search(r"^COUNTER=([0-9]+)$", installer, re.M)
    native_ota.need(component is not None and counter is not None, "Missing component identity")
    install_sha = hashlib.sha256(entries["ssh703t/install.sh"][0]).hexdigest()
    wrapper = (ROOT / "tools/ssh703t/ota-bootstrap.sh").read_text().replace("__INSTALL_SHA__", install_sha).encode()
    assert b"__INSTALL_SHA__" not in wrapper
    for name in ENTRYPOINTS:
        entries[name] = (wrapper, 0o755)
    with tempfile.TemporaryDirectory(prefix="703t-ssh-bootstrap-") as tmp:
        source = Path(tmp) / "source.tar"
        with tarfile.open(source, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, (body, mode) in sorted(entries.items()):
                header = tarfile.TarInfo(name)
                header.size, header.mode = len(body), mode
                archive.addfile(header, io.BytesIO(body))
        result = native_ota.build(source, output, private_key,
                                  "incremental", release, "JC_703T25_V02.26.02.02.60",
                                  "ssh703t/payload/post-install-test.sh", "ssh703t/payload/rollback.sh")
    result.update(component_release=component[1], component_counter=int(counter[1]), source_sha256=expected_sha,
                  changed_members=sorted(ENTRYPOINTS),
                  factory_tail_handling="sync and terminal Linux reboot; hold if reboot fails",
                  physical_instrument_tested=False)
    output.with_suffix(".build.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=SOURCE)
    p.add_argument("--source-sha256", default=SOURCE_SHA, help="Reviewed component TAR SHA-256")
    p.add_argument("--output", type=Path, default=OUTPUT)
    p.add_argument("--release", default="ssh-20261115-bootstrap2")
    p.add_argument("--public-key", type=Path, default=ROOT / "android/assets/release-public.pem")
    p.add_argument("--private-key", type=Path, default=ROOT / "android/.firmware-signing/release-private.pem")
    a = p.parse_args()
    if a.input.resolve() != SOURCE.resolve() and (a.output == OUTPUT or a.release == "ssh-20261115-bootstrap2"):
        p.error("New component requires a distinct --output and --release; do not reuse the verified historical identity")
    result = build(a.input, a.source_sha256, a.output, a.release, a.public_key, a.private_key)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
