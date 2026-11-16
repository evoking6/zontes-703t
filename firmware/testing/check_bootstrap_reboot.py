#!/usr/bin/env python3
"""Reboot ONLY the isolated emulator with original BusyBox's reboot -f.

Requires check_incremental_rollback.py's loopback fixture installed and running.
Validates the new entrypoint cannot return into a factory-like waiting parent,
then re-mounts the isolated chroot and invokes its normal S97 startup hook.
No original Launcher or MCU code is executed. Physical devices are rejected.
"""
import hashlib
import importlib.util
from pathlib import Path
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("checks", Path(__file__).with_name("check_incremental_rollback.py"))
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


def main():
    assert device.adb("shell", "getprop ro.kernel.qemu").stdout.strip() == "1"
    assert device.adb("shell", "id -u").stdout.strip() == "0"
    assert device.adb("shell", "uname -m").stdout.strip() == "aarch64"
    runtime = "/opt/703t-ssh/releases/" + device.RELEASE
    assert "127.0.0.1:2222" in device.shell("cat " + runtime + "/service.sh").stdout
    before = device.adb("shell", "cat /proc/sys/kernel/random/boot_id").stdout.strip()
    hostkey = device.shell("sha256sum /opt/703t-ssh/hostkeys/ed25519").stdout
    original = device.original()
    with tarfile.open(device.BUNDLE) as archive:
        body = archive.extractfile("updateFile_GT.sh").read().decode()
        install_sha = hashlib.sha256(archive.extractfile("ssh703t/install.sh").read()).hexdigest()
    fixture_sha = device.shell("sha256sum /etc/updateFile/ssh703t/install.sh").stdout.split()[0]
    body = body.replace(install_sha, fixture_sha)  # Fixture differs only for panel/AP emulation.
    local = ROOT / "firmware/testing/generated/TEST-ONLY-real-reboot-entry.sh"
    local.write_text(body)
    for name in ("updateFile.sh", "updateFile_GT.sh", "updateFile_HW.sh"):
        device.adb("push", str(local), device.REMOTE + "/etc/updateFile/" + name)
    device.shell("rm -f /fixture/ota-parent-resumed")
    device.shell("/bin/sh /etc/updateFile/updateFile_GT.sh; echo BAD_PARENT_RESUMED > /fixture/ota-parent-resumed", check=False, timeout=20)
    print("Kernel reboot requested by real entrypoint; waiting for isolated emulator", flush=True)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        probe = device.adb("shell", "cat /proc/sys/kernel/random/boot_id; getprop sys.boot_completed", check=False, timeout=5)
        rows = probe.stdout.splitlines()
        if probe.returncode == 0 and len(rows) == 2 and rows[0] != before and rows[1] == "1":
            break
        time.sleep(.5)
    else:
        raise RuntimeError("Isolated emulator did not complete reboot")
    device.adb("root")
    device.adb("wait-for-device")
    assert device.adb("shell", "getprop ro.kernel.qemu").stdout.strip() == "1"
    device.adb("shell", "setenforce 0")
    r = device.REMOTE
    device.adb("shell", "mount -t tmpfs -o mode=0755 tmpfs " + r + "/dev; mkdir -p " + r + "/dev/pts")
    for name, major, minor in (("null", 1, 3), ("zero", 1, 5), ("random", 1, 8), ("urandom", 1, 9), ("tty", 5, 0)):
        device.adb("shell", f"mknod {r}/dev/{name} c {major} {minor}; chmod 666 {r}/dev/{name}")
    device.adb("shell", "mount -t devpts -o newinstance,ptmxmode=0666,mode=0620 devpts " + r + "/dev/pts; ln -s pts/ptmx " + r + "/dev/ptmx")
    device.adb("shell", "mount --bind /proc " + r + "/proc")
    device.shell("test ! -e /fixture/ota-parent-resumed; test ! -e /etc/updateFile/updateFile.sh; test ! -e /etc/updateFile/updateFile_GT.sh; test ! -e /etc/updateFile/updateFile_HW.sh")
    # /tmp is RAM on the instrument; discard the emulator fixture's persisted /tmp.
    device.shell("rm -rf /tmp/703t-ssh /tmp/703t-ssh-install.lock; /etc/init.d/S97ssh703t start")
    device.shell(runtime + "/post-install-test.sh")
    assert original == device.original()
    assert hostkey == device.shell("sha256sum /opt/703t-ssh/hostkeys/ed25519").stdout
    print("PASS actual emulator kernel reboot changed boot ID, waiting parent never resumed, replay entries removed", flush=True)
    print("PASS SSH startup hook and real post-install checks after reboot; original files and host identity unchanged", flush=True)


if __name__ == "__main__":
    main()
