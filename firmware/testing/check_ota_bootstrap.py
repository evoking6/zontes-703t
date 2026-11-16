#!/usr/bin/env python3
"""Check the OTA entrypoint under the original BusyBox on emulator-5556 only.

Only the entrypoint is exercised here. Installer outcomes and reboot failure are
injected in a private fixture; no reboot command is executed by these tests.
The separate transactional suite tests the actual SSH installer and rollback.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import shlex
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("rollback_checks", Path(__file__).with_name("check_incremental_rollback.py"))
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)
BASE = "/fixture/ota-bootstrap"


def put(name, body):
    local = ROOT / "firmware/testing/generated" / ("bootstrap-" + name)
    local.write_text(body)
    device.adb("push", str(local), device.REMOTE + BASE + "/" + name)


def run_case(wrapper, result):
    device.shell("rm -rf " + BASE + "; mkdir -p " + BASE + "/updateFile/ssh703t")
    installer = "#!/bin/sh\nprintf '%s\\n' INSTALL_CALLED > " + BASE + "/installed\nexit " + str(result) + "\n"
    put("install.sh", installer)
    device.shell("cp " + BASE + "/install.sh " + BASE + "/updateFile/ssh703t/install.sh")
    # Fixture injection is confined to this test copy, never to a signed archive.
    changed = wrapper.replace("/etc/updateFile", BASE + "/updateFile")
    changed = changed.replace("/tmp/703t-ssh-bootstrap.log", BASE + "/bootstrap.log")
    import re
    changed = re.sub(r"[a-f0-9]{64}  /fixture/ota-bootstrap/updateFile/ssh703t/install.sh",
                     hashlib.sha256(installer.encode()).hexdigest() + "  " + BASE + "/updateFile/ssh703t/install.sh", changed)
    changed = changed.replace("/bin/busybox reboot -f", "/bin/sh " + BASE + "/reboot.sh")
    put("entry.sh", changed)
    put("reboot.sh", "#!/bin/sh\necho REBOOT_REQUESTED > " + BASE + "/reboot-requested\nexit 1\n")
    for entry in ("updateFile.sh", "updateFile_GT.sh", "updateFile_HW.sh"):
        device.shell("cp " + BASE + "/entry.sh " + BASE + "/updateFile/" + entry)
    parent = ("#!/bin/sh\necho $$ > " + BASE + "/parent.pid\n/bin/sh " + BASE + "/updateFile/updateFile_GT.sh\n"
              "echo PARENT_CONTINUED > " + BASE + "/parent-continued\n")
    put("parent.sh", parent)
    device.shell("setsid /bin/sh " + BASE + "/parent.sh > " + BASE + "/parent.log 2>&1 < /dev/null &")
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = device.shell("ls " + BASE).stdout.splitlines()
            if "parent-continued" in state or "reboot-requested" in state:
                break
            time.sleep(.1)
        assert "parent-continued" not in state, "Factory parent resumed after installer exit " + str(result)
        assert "installed" in state, "Installer was not invoked"
        assert "reboot-requested" in state, "No controlled restart request"
        device.shell("test ! -e " + BASE + "/updateFile/updateFile.sh; test ! -e " + BASE + "/updateFile/updateFile_GT.sh; test ! -e " + BASE + "/updateFile/updateFile_HW.sh")
        print("PASS installer exit " + str(result) + ": replay entrypoints removed, restart requested, reboot failure does not resume factory parent", flush=True)
    finally:
        device.shell("if [ -f " + BASE + "/parent.pid ]; then p=$(cat " + BASE + "/parent.pid); kill -KILL -$p 2>/dev/null || :; fi")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    assert device.adb("shell", "getprop ro.kernel.qemu").stdout.strip() == "1"
    assert device.adb("shell", "id -u").stdout.strip() == "0"
    assert device.adb("shell", "uname -m").stdout.strip() == "aarch64"
    with tarfile.open(args.archive) as archive:
        wrapper = archive.extractfile("updateFile_GT.sh").read().decode()
        assert all(archive.extractfile(name).read().decode() == wrapper for name in ("updateFile_HW.sh", "updateFile.sh"))
    for result in (0, 1, 19):
        run_case(wrapper, result)
    print("PASS 3 OTA entrypoint lifecycle checks; original BusyBox, simulated installer/reboot, emulator only")


if __name__ == "__main__":
    main()
