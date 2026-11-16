#!/usr/bin/env python3
"""Build a signed standalone APK with the installed SDK; no Gradle/network downloads.

Signing material is generated once in .signing/ and is never packaged in the APK.
Keep that directory privately for future updates signed with the same identity.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from release_key import ensure_release_key, public_key_id

ROOT = Path(__file__).resolve().parent
# com.google.zxing:core:3.5.4, Apache-2.0. Kept locally for offline builds.
ZXING = ROOT / "libs/zxing-core-3.5.4.jar"
ZXING_SHA256 = "71de5d89341b5fcf5dd89da7f44e84d825d0e084cdf3ec77c9abe26b0f0ceb13"


def run(command, env, capture=False):
    result = subprocess.run([str(s) for s in command], env=env, check=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    return result.stdout.decode() if capture else ""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sdk", default=os.environ.get("ANDROID_SDK_ROOT", str(Path.home() / "Library/Android/sdk")))
    p.add_argument("--java-home", default=os.environ.get("JAVA_HOME", "/Library/Java/JavaVirtualMachines/jdk-17.jdk/Contents/Home"))
    p.add_argument("--debug", action="store_true")
    p.add_argument("--test-public-key", help="Isolated test-only APK with a fixture trust key; never written to dist")
    a = p.parse_args()
    sdk, java = Path(a.sdk), Path(a.java_home)
    platform = sdk / "platforms/android-37.0/android.jar"
    if not platform.is_file():
        platform = sdk / "platforms/android-37/android.jar"
    build_tools = sdk / "build-tools/36.0.0"
    if not platform.is_file() or not (build_tools / "aapt2").is_file():
        p.error("Requires Android SDK platform 37 and build-tools 36.0.0 (or adjust the script for installed versions)")
    env = dict(os.environ, JAVA_HOME=str(java))
    env["PATH"] = str(java / "bin") + os.pathsep + env.get("PATH", "")
    if a.debug and a.test_public_key: p.error("Choose either debug or test-only build")
    if not ZXING.is_file() or hashlib.sha256(ZXING.read_bytes()).hexdigest() != ZXING_SHA256:
        p.error("ZXing QR dependency is missing or has a different checksum")
    build = ROOT / "build" / ("test-target" if a.test_public_key else "debug" if a.debug else "release")
    if build.exists(): shutil.rmtree(build)
    for name in ("classes", "generated", "dex", "assets"):
        (build / name).mkdir(parents=True, exist_ok=True)
    manifest = (ROOT / "AndroidManifest.xml").read_text()
    ns = "{http://schemas.android.com/apk/res/android}"
    version = ET.fromstring(manifest).get(ns + "versionName")
    if a.test_public_key:
        test_key = Path(a.test_public_key).resolve()
        key_id = public_key_id(test_key)
        shutil.copyfile(test_key, build / "assets/release-public.pem")
        manifest = manifest.replace('<application ', '<application android:testOnly="true" ', 1)
        manifest = manifest.replace('android:label="703T 仪表更新"', 'android:label="703T 仪表更新（测试）"')
    else:
        identity = ensure_release_key(ROOT)
        key_id = identity["key_id"]
        shutil.copyfile(identity["public"], build / "assets/release-public.pem")
    shutil.copytree(ROOT / "assets/licenses", build / "assets/licenses")
    if a.debug: manifest = manifest.replace('android:debuggable="false"', 'android:debuggable="true"')
    (build / "AndroidManifest.xml").write_text(manifest)
    run([build_tools / "aapt2", "compile", "--dir", ROOT / "res", "-o", build / "resources.zip"], env)
    run([build_tools / "aapt2", "link", "-I", platform, "--manifest", build / "AndroidManifest.xml",
         "--java", build / "generated", "-A", build / "assets", "-o", build / "resources.apk", build / "resources.zip"], env)
    sources = sorted((ROOT / "src").rglob("*.java")) + sorted((build / "generated").rglob("*.java"))
    args_file = build / "javac.args"
    args_file.write_text("\n".join('"' + str(source).replace('\\', '\\\\').replace('"', '\\"') + '"' for source in sources))
    run([java / "bin/javac", "-encoding", "UTF-8", "--release", "8", "-classpath", os.pathsep.join(map(str, (platform, ZXING))),
         "-d", build / "classes", "@" + str(args_file)], env)
    with zipfile.ZipFile(build / "classes.jar", "w") as jar:
        for file in sorted((build / "classes").rglob("*.class")): jar.write(file, file.relative_to(build / "classes"))
    run([build_tools / "d8", "--release", "--min-api", "29", "--lib", platform,
         "--output", build / "dex", build / "classes.jar", ZXING], env)
    shutil.copyfile(build / "resources.apk", build / "unsigned.apk")
    with zipfile.ZipFile(build / "unsigned.apk", "a", compression=zipfile.ZIP_DEFLATED) as apk:
        for file in (build / "dex").glob("*.dex"): apk.write(file, file.name)
    run([build_tools / "zipalign", "-P", "16", "-f", "4", build / "unsigned.apk", build / "aligned.apk"], env)
    signing = ROOT / ".signing"
    signing.mkdir(mode=0o700, exist_ok=True)
    password, keystore = signing / "password.txt", signing / "703t-app.p12"
    if not password.exists():
        if keystore.exists(): p.error("Signing password file missing; refusing to replace the signing identity")
        fd = os.open(password, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as f: f.write(os.urandom(24).hex())
    if not keystore.exists():
        run([java / "bin/keytool", "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12",
             "-storepass:file", password, "-keypass:file", password, "-alias", "703t-android-app",
             "-keyalg", "RSA", "-keysize", "3072", "-validity", "10000", "-dname", "CN=703T Local Android Build"], env)
        keystore.chmod(0o600)
    dist = ROOT.parent / "dist"
    dist.mkdir(exist_ok=True)
    output = build / "test-target.apk" if a.test_public_key else dist / ("703T-OTA-" + version + ("-debug" if a.debug else "") + ".apk")
    run([build_tools / "apksigner", "sign", "--ks", keystore, "--ks-key-alias", "703t-android-app",
         "--ks-pass", "file:" + str(password), "--out", output, build / "aligned.apk"], env)
    report = run([build_tools / "apksigner", "verify", "--verbose", "--print-certs", output], env, capture=True)
    (build / "signature-verification.txt").write_text(report)
    if not a.test_public_key:
        (dist / "APK-signature-verification.txt").write_text(report)
        shutil.copyfile(identity["public"], dist / "release-public.pem")
        (dist / "release-public-key-id.txt").write_text(key_id + "\n")
    run([build_tools / "zipalign", "-c", "-P", "16", "4", output], env)
    sha = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.parent / (output.name + ".sha256")).write_text(sha + "  " + output.name + "\n")
    print(json.dumps({"apk": str(output), "bytes": output.stat().st_size, "sha256": sha,
                      "min_sdk": 29, "target_sdk": 37, "debuggable": a.debug,
                      "firmware_release_key_id": key_id, "test_only": bool(a.test_public_key)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
