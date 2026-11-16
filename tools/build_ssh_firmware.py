#!/usr/bin/env python3
"""Build the baseline-bound SSH-only 703T candidate. No device access or flashing."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request
import sys

ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026.94"
SOURCE_SHA = "e098034a843699200c8c977a991fff73159735bf795d5f72ef672c41a6b1ae81"
FACTORY_SHA = "4fd51af4f1d2dd4f72acf2141cb885043f0a67d1fcdf5065704f69bb485e86ea"
LAUNCHER_SHA = "5c50de0b8df71e407d3206bb2cb24d59fd60d7f6174a145b320937659c5bab11"
RELEASE = "ssh-20261115-4"
COUNTER = 4
EPOCH = 1793116800
TEMPLATES = ROOT / "tools/ssh703t"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def dropbear():
    base = ROOT / ".tools/ssh703t"
    base.mkdir(parents=True, exist_ok=True)
    archive = base / ("dropbear-" + VERSION + ".tar.bz2")
    url = "https://dropbear.nl/mirror/releases/" + archive.name
    if not archive.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            archive.write_bytes(response.read(8 * 1024 * 1024))
    if sha(archive.read_bytes()) != SOURCE_SHA:
        raise RuntimeError("Dropbear source SHA256 mismatch")
    src = base / ("dropbear-" + VERSION)
    if not src.is_dir():
        with tarfile.open(archive) as tar:
            for entry in tar.getmembers():
                if entry.name.startswith("/") or ".." in Path(entry.name).parts or not (entry.isfile() or entry.isdir()):
                    raise RuntimeError("Unexpected source archive member")
            tar.extractall(base)
    binary = src / "dropbearmulti"
    config = (TEMPLATES / "localoptions.h").read_bytes()
    state = base / "build-state.json"
    expected = {"source_sha256": SOURCE_SHA, "options_sha256": sha(config)}
    previous = json.loads(state.read_text()) if state.exists() else {}
    if binary.exists() and all(previous.get(k) == v for k, v in expected.items()) and previous.get("binary_sha256") == sha(binary.read_bytes()):
        return binary, {**previous, "source_url": url}
    cc = shutil.which("aarch64-linux-musl-gcc") or "/opt/homebrew/bin/aarch64-linux-musl-gcc"
    if not Path(cc).is_file():
        raise RuntimeError("Install/configure an AArch64 Linux musl GCC toolchain first")
    prefix = cc.removesuffix("gcc")
    env = dict(os.environ, CC=cc, AR=prefix + "ar", RANLIB=prefix + "ranlib", STRIP=prefix + "strip",
               CFLAGS="-Os -fstack-protector-strong -D_FORTIFY_SOURCE=2")
    if (src / "Makefile").exists():
        run(["make", "clean"], cwd=src, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    (src / "localoptions.h").write_bytes(config)
    with (base / "configure.log").open("w") as log:
        run(["./configure", "--host=aarch64-linux-musl", "--enable-static", "--disable-zlib", "--disable-syslog",
             "--disable-lastlog", "--disable-utmp", "--disable-utmpx", "--disable-wtmp", "--disable-wtmpx"],
            cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT)
    with (base / "make.log").open("w") as log:
        run(["make", "-j4", "PROGRAMS=dropbear dropbearkey", "MULTI=1", "STATIC=1"],
            cwd=src, env=env, stdout=log, stderr=subprocess.STDOUT)
    run([prefix + "strip", binary])
    data = binary.read_bytes()
    if data[:6] != b"\x7fELF\x02\x01" or int.from_bytes(data[18:20], "little") != 183:
        raise RuntimeError("Expected AArch64 ELF64 executable")
    headers = run([prefix + "readelf", "-l", binary], capture_output=True, text=True).stdout
    if "INTERP" in headers or "DYNAMIC" in headers:
        raise RuntimeError("Expected a static executable without a runtime linker")
    result = {**expected, "binary_sha256": sha(data), "compiler": run([cc, "--version"], capture_output=True, text=True).stdout.splitlines()[0]}
    state.write_text(json.dumps(result, indent=2) + "\n")
    return binary, {**result, "source_url": url}


def access_key():
    directory = ROOT / "firmware/.ssh-access"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    key = directory / "id_ed25519"
    if not key.exists():
        if key.with_suffix(".pub").exists():
            raise RuntimeError("SSH public key exists but private key is missing; refusing to change identity")
        run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "703t-owner-maintenance", "-f", key])
    key.chmod(0o600)
    fields = run(["ssh-keygen", "-y", "-f", key], capture_output=True).stdout.split()
    public = b" ".join(fields[:2]) + b" 703t-owner-maintenance\n"
    key.with_suffix(".pub").write_bytes(public)
    return key, public


def main():
    sys.path.insert(0, str(ROOT / "android"))
    from release_key import ensure_release_key
    identity = ensure_release_key(ROOT / "android")
    if identity["private"] is None:
        raise RuntimeError("Firmware signing private key missing; restore your original private identity")
    factory = ROOT / "JC_703T25_V02.26.02.02.60.tar"
    if sha(factory.read_bytes()) != FACTORY_SHA:
        raise RuntimeError("Factory archive changed")
    with tarfile.open(factory) as tar:
        launcher = tar.extractfile("Launcher").read()
        assert sha(launcher) == LAUNCHER_SHA
        rc_hashes = [sha(tar.extractfile("etc/init.d/" + name).read()) for name in ("rcS", "rcS_bak", "rcS1")]
    binary, provenance = dropbear()
    private, public = access_key()

    def template(name, **replacements):
        text = (TEMPLATES / name).read_text().replace("__RELEASE__", RELEASE).replace("__COUNTER__", str(COUNTER))
        text = text.replace("__LAUNCHER_SHA__", LAUNCHER_SHA).replace("__RCS_HASHES__", "|".join(rc_hashes))
        for k, v in replacements.items():
            text = text.replace("__" + k + "__", v)
        return text.encode()

    payload = {
        "dropbearmulti": (binary.read_bytes(), 0o755),
        "service.sh": (template("service.sh"), 0o755),
        "S97ssh703t": (template("S97ssh703t"), 0o755),
        "disable.sh": (template("disable.sh"), 0o755),
        "keys/authorized_keys": (public, 0o600),
        "LICENSE.dropbear": (b"\n\n".join((binary.parent / name).read_bytes() for name in
                            ("LICENSE", "libtomcrypt/LICENSE", "libtommath/LICENSE")) +
                            b"\n\nStatic musl libc license:\n\n" + (TEMPLATES / "LICENSE.musl").read_bytes(), 0o644),
    }
    for name in ("post-install-test.sh", "health-controller.sh", "rollback.sh"):
        payload[name] = (template(name), 0o755)
    checksums = "".join(f"{sha(data)}  {name}\n" for name, (data, _) in sorted(payload.items())).encode()
    payload["SHA256SUMS"] = (checksums, 0o644)
    entries = {"ssh703t/payload/" + name: value for name, value in payload.items()}
    entries["ssh703t/install.sh"] = (template("install.sh", LAUNCHER_SHA=LAUNCHER_SHA,
                                                RCS_HASHES="|".join(rc_hashes), CHECKSUMS_SHA=sha(checksums)), 0o755)
    wrapper = b'#!/bin/sh\n# 703T_SSH_MANAGED_V1\nexec /bin/sh /etc/updateFile/ssh703t/install.sh\n'
    for name in ("updateFile.sh", "updateFile_GT.sh", "updateFile_HW.sh"):
        entries[name] = (wrapper, 0o755)
    build = ROOT / "firmware/build" / RELEASE
    if build.exists(): shutil.rmtree(build)
    build.mkdir(parents=True)
    output = ROOT / "dist/JC_703T25_SSH_0.1.4_CANDIDATE.tar"
    output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output, "w", format=tarfile.USTAR_FORMAT) as tar:
        for name, (data, mode) in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, EPOCH
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            tar.addfile(info, io.BytesIO(data))
            file = build / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
            file.chmod(mode)
    output.with_suffix(".tar.sha256").write_text(sha(output.read_bytes()) + "  " + output.name + "\n")
    # Detached release signature is for offline verification; the factory updater does not verify it.
    signer = ROOT / "android/.firmware-signing/release-private.pem"
    if not signer.exists(): raise RuntimeError("Firmware signing private key missing")
    run(["openssl", "dgst", "-sha256", "-sign", signer, "-out", str(output) + ".sig", output])
    run(["openssl", "dgst", "-sha256", "-verify", ROOT / "android/assets/release-public.pem",
         "-signature", str(output) + ".sig", output], stdout=subprocess.DEVNULL)
    metadata = {"artifact": output.name, "release": RELEASE, "bytes": output.stat().st_size,
                "sha256": sha(output.read_bytes()), "factory_sha256": FACTORY_SHA, "launcher_sha256": LAUNCHER_SHA,
                "allowed_rcS_sha256": rc_hashes, "dropbear": {"version": VERSION, **provenance},
                "ssh_login_public_key_fingerprint": run(["ssh-keygen", "-lf", private.with_suffix(".pub")], capture_output=True, text=True).stdout.strip(),
                "listen": "192.168.3.1:22", "interface": "wlan0", "password_auth_compiled": True,
                "full_system_image": False, "kernel_boot_mcu_payloads_included": False,
                "factory_installer_side_effects_eliminated": False, "physical_instrument_tested": False,
                "android_apk_accepts_this_tar": False,
                "usage": "SSH maintenance component; requires terminal bootstrap and native manifest for factory OTA",
                "validation_profile": "ssh-post-install-v1", "validation_timeout_seconds": 60,
                "rollback_profile": "ssh-activation-v1", "component_counter": COUNTER, "members": sorted(entries)}
    (ROOT / "dist/SSH固件构建记录.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"candidate": str(output), "bytes": output.stat().st_size, "sha256": metadata["sha256"],
                      "ssh_private_key": str(private), "physical_instrument_tested": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
