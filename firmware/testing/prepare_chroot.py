#!/usr/bin/env python3
"""Prepare a task-owned chroot on emulator-5556; no physical-device support."""
from pathlib import Path
import shutil
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "firmware/testing/generated"
SDK = Path.home() / "Library/Android/sdk"
ADB = SDK / "platform-tools/adb"
REMOTE = "/data/local/tmp/703t-ssh-root"


def adb(*args, check=True):
    return subprocess.run([str(ADB), "-s", "emulator-5556", *args], check=check,
                          capture_output=True, text=True, timeout=45)


def main():
    assert adb("shell", "getprop ro.kernel.qemu").stdout.strip() == "1"
    assert adb("shell", "uname -m").stdout.strip() == "aarch64"
    assert adb("shell", "id -u").stdout.strip() == "0", "Use adb -s emulator-5556 root first"
    if adb("shell", "test -e " + REMOTE, check=False).returncode == 0:
        raise SystemExit("Chroot already exists; use a fresh task emulator or remove this task's stopped chroot explicitly")
    base = OUT / "chroot"
    if base.exists(): shutil.rmtree(base)
    for directory in ("bin", "sbin", "usr/bin", "usr/sbin", "lib", "etc/init.d", "dev/pts", "proc", "sys", "tmp", "var/run", "root", "opt"):
        (base / directory).mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "analysis/ramdisk/GT/bin/busybox", base / "bin/busybox")
    (base / "bin/busybox").chmod(0o755)
    for file in (ROOT / "analysis/ramdisk/GT/lib").iterdir():
        if file.is_file(): shutil.copy2(file, base / "lib" / file.name)
    (base / "lib/ld-linux-aarch64.so.1").chmod(0o755)
    (base / "lib64").symlink_to("lib")  # The original initramfs has this symlink.
    shutil.copyfile(ROOT / "analysis/original/Launcher", base / "usr/bin/Launcher")
    shutil.copyfile(ROOT / "analysis/original/etc/init.d/rcS", base / "etc/init.d/rcS")
    (base / "etc/passwd").write_text("root:x:0:0:root:/root:/bin/sh\nnobody:x:65534:65534:nobody:/tmp:/bin/sh\n")
    (base / "etc/shadow").write_text("root:*:0:0:99999:7:::\nnobody:*:0:0:99999:7:::\n")
    (base / "etc/shadow").chmod(0o600)
    (base / "etc/group").write_text("root:x:0:\nnogroup:x:65534:\n")
    (base / "etc/shells").write_text("/bin/sh\n")
    (base / "proc/lcdv").write_text("GT_G080-11\n")
    archive = OUT / "chroot.tar"
    with tarfile.open(archive, "w") as tar:
        for file in sorted(base.rglob("*")):
            info = tar.gettarinfo(file, file.relative_to(base).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            if file.is_file() and not file.is_symlink():
                with file.open("rb") as stream: tar.addfile(info, stream)
            else: tar.addfile(info)
    adb("push", str(archive), "/data/local/tmp/703t-ssh-chroot.tar")
    adb("shell", "setenforce 0")  # Isolated emulator only; physical devices are rejected above.
    adb("shell", "mkdir -p " + REMOTE + "; chmod 755 " + REMOTE +
        "; tar xf /data/local/tmp/703t-ssh-chroot.tar -C " + REMOTE)
    # Private devices/devpts keep the chroot independent of Android adbd PTYs.
    # /data is mounted nodev, so devices need their own tmpfs mount.
    adb("shell", "mount -t tmpfs -o mode=0755 tmpfs " + REMOTE + "/dev; mkdir -p " + REMOTE + "/dev/pts")
    for name, major, minor in (("null", 1, 3), ("zero", 1, 5), ("random", 1, 8), ("urandom", 1, 9), ("tty", 5, 0)):
        adb("shell", f"mknod {REMOTE}/dev/{name} c {major} {minor}; chmod 666 {REMOTE}/dev/{name}")
    adb("shell", "mount -t devpts -o newinstance,ptmxmode=0666,mode=0620 devpts " + REMOTE + "/dev/pts")
    adb("shell", "ln -s pts/ptmx " + REMOTE + "/dev/ptmx")
    # Preserve BusyBox's FHS destinations; forcing all links into /bin masked
    # the production setsid location (/usr/bin/setsid).
    adb("shell", "PATH=/bin:/usr/bin:/sbin /system/bin/chroot " + REMOTE + " /bin/busybox --install -s")
    print("Task-owned Linux chroot ready; original Launcher/rcS are data for hashing and are never executed.")


if __name__ == "__main__":
    main()
