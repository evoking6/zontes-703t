#!/usr/bin/env python3
"""Isolated ARM64 chroot checks using original BusyBox/libs and release Dropbear.

Never runs Launcher/rcS or factory updater. Test-only package variants replace
panel input and AP binding, and inject failure/hang for recovery checks.
No release private key is used and no test package is placed in dist.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import re
import subprocess
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
ADB = Path.home() / 'Library/Android/sdk/platform-tools/adb'
REMOTE = '/data/local/tmp/703t-ssh-root'
OUT = ROOT / 'firmware/testing/generated'
BUNDLE = Path(os.environ.get('SSH703T_TEST_BUNDLE', str(ROOT / 'dist/JC_703T25_SSH_NATIVE_0.1.3_CANDIDATE.tar')))
with tarfile.open(BUNDLE) as _archive:
    _installer = _archive.extractfile('ssh703t/install.sh').read().decode()
RELEASE = re.search(r'^RELEASE=(\S+)$', _installer, re.M).group(1)
COUNTER = int(re.search(r'^COUNTER=(\d+)$', _installer, re.M).group(1))
OLD = 'ssh-simulator-old'
BASE = '/opt/703t-ssh'
HOOK = '/etc/init.d/S97ssh703t'
passed = []


def adb(*args, check=True, timeout=100):
    return subprocess.run([str(ADB), '-s', 'emulator-5556', *args], check=check,
                          capture_output=True, text=True, timeout=timeout)


def shell(cmd, check=True, timeout=100):
    return adb('shell', 'PATH=/bin:/usr/bin:/sbin:/usr/sbin /system/bin/chroot ' + REMOTE + ' /bin/sh -c ' + shlex.quote(cmd), check=check, timeout=timeout)


def ok(message):
    passed.append(message); print('PASS ' + message, flush=True)


def sha(data): return hashlib.sha256(data).hexdigest()


def package(name, failure=None, previous=False, production_binding=False, slow_key=False):
    with tarfile.open(BUNDLE) as tar:
        # Test variants deliberately alter payloads, so do not retain the release signature.
        rows = {m.name: [tar.extractfile(m).read(), m.mode] for m in tar.getmembers() if not m.name.startswith('ota703t/')}
    for path, row in rows.items():
        if path.endswith('.sh') or path.endswith('S97ssh703t'):
            text = row[0].decode().replace('/proc/lcdv', '/fixture/lcdv')
            if not production_binding:
                text = text.replace('192.168.3.1:22', '127.0.0.1:2222').replace('-l wlan0', '-l lo').replace('0103A8C0:0016', '0100007F:08AE')
            if previous:
                text = text.replace(RELEASE, OLD).replace('COUNTER=' + str(COUNTER), 'COUNTER=1').replace("'" + str(COUNTER) + "' >", "'1' >")
            if slow_key and path.endswith('/service.sh'):
                text = text.replace('if [ ! -s "$HOST" ]; then', 'if [ ! -s "$HOST" ]; then\n        sleep 2')
            row[0] = text.encode()
    if failure:
        test = '#!/bin/sh\n' + ('echo INJECTED_TEST_FAILURE; exit 19\n' if failure == 'exit' else "trap '' TERM\necho INJECTED_HANG\nsleep 90\nexit 19\n")
        rows['ssh703t/payload/post-install-test.sh'][0] = test.encode()
    prefix = 'ssh703t/payload/'
    manifest = ''.join(f'{sha(data)}  {path[len(prefix):]}\n' for path, (data, mode) in sorted(rows.items()) if path.startswith(prefix) and not path.endswith('/SHA256SUMS')).encode()
    old = rows[prefix + 'SHA256SUMS'][0]
    rows[prefix + 'SHA256SUMS'][0] = manifest
    rows['ssh703t/install.sh'][0] = rows['ssh703t/install.sh'][0].replace(sha(old).encode(), sha(manifest).encode())
    path = OUT / ('TEST-ONLY-' + name + '.tar')
    with tarfile.open(path, 'w', format=tarfile.USTAR_FORMAT) as tar:
        for key, (data, mode) in sorted(rows.items()):
            m = tarfile.TarInfo(key); m.size = len(data); m.mode = mode
            tar.addfile(m, io.BytesIO(data))
    adb('push', str(path), REMOTE + '/tmp/TEST-ONLY-incremental.tar')
    shell('rm -rf /etc/updateFile; mkdir -p /etc/updateFile; tar xf /tmp/TEST-ONLY-incremental.tar -C /etc/updateFile')


def install(): return shell('/bin/sh /etc/updateFile/ssh703t/install.sh', check=False)


def result():
    raw = shell('cat ' + BASE + '/transactions/txn-' + RELEASE + '-*/result.json').stdout
    return json.loads(raw)


def reset():
    shell('if [ -f ' + HOOK + ' ]; then ' + HOOK + ' stop; fi')
    time.sleep(.4)
    shell('test ! -f /tmp/703t-ssh/supervisor/pid; rm -rf /opt/703t-ssh /tmp/703t-ssh /tmp/703t-ssh-install.lock; rm -f ' + HOOK)


def no_listener():
    shell("! grep -Eq '[[:space:]]0100007F:08AE[[:space:]]+[[:xdigit:]]+:[[:xdigit:]]+[[:space:]]+0A[[:space:]]' /proc/net/tcp")


def original(): return shell('sha256sum /usr/bin/Launcher /etc/init.d/rcS').stdout


def main():
    assert adb('shell', 'getprop ro.kernel.qemu').stdout.strip() == '1'
    assert adb('shell', 'uname -m').stdout.strip() == 'aarch64'
    assert adb('shell', 'id -u').stdout.strip() == '0'
    adb('shell', 'mount --bind /proc ' + REMOTE + '/proc')
    shell("mkdir -p /fixture; printf 'GT_G080-11\\n' > /fixture/lcdv")
    baseline = original()
    reset(); package('success', slow_key=True)
    shell("printf 'UNKNOWN\\n' > /fixture/lcdv")
    assert install().returncode != 0
    shell('test ! -e ' + BASE + '; test ! -e ' + HOOK)
    ok('Unknown panel rejected before persistent installation')
    shell("printf 'GT_G080-11\\n' > /fixture/lcdv; printf corrupt >> /etc/updateFile/ssh703t/payload/rollback.sh")
    assert install().returncode != 0
    shell('test ! -e ' + BASE)
    ok('Corrupt rollback payload rejected before installation')
    package('security-checks', slow_key=True)
    shell('ln -s /opt /tmp/703t-ssh-install.lock')
    rejected = install(); assert rejected.returncode != 0 and 'refusing symlink' in rejected.stderr, rejected.stderr
    shell('test ! -e ' + BASE + '; rm /tmp/703t-ssh-install.lock; mkdir -p ' + BASE + '; chmod 777 ' + BASE)
    rejected = install(); assert rejected.returncode != 0 and 'group/other writable ancestor' in rejected.stderr, rejected.stderr
    shell('rm -rf ' + BASE)
    ok('Symlink installation lock and writable preexisting component directory are rejected before writes')
    package('success', slow_key=True)
    for panel in ('GT_G080-11', 'HW_TFT080X', 'HW_CLAA080'):
        shell("printf '%s\\n' " + panel + ' > /fixture/lcdv')
        installed = install(); assert installed.returncode == 0, installed.stdout + installed.stderr
    assert result()['phase'] == 'COMMITTED' and result()['validation_passed']
    ok('All three panels pass real post-install checks; first-key delay is tolerated and repeat installation revalidates')
    assert original() == baseline
    ok('Original Launcher and rcS remain byte-identical')
    host = shell('sha256sum ' + BASE + '/hostkeys/ed25519').stdout
    reset(); package('first-install-failure', 'exit')
    failed = install(); assert failed.returncode != 0 and result()['phase'] == 'ROLLED_BACK' and result()['rollback_verified'], failed.stdout + failed.stderr
    shell('test ! -e ' + HOOK + '; test ! -e ' + BASE + '/component-state; test ! -e ' + BASE + '/pending')
    no_listener(); ok('Failed first installation removes new activation, stops candidate and verifies rollback')
    reset(); package('old-success', previous=True)
    installed = install(); assert installed.returncode == 0, installed.stdout + installed.stderr
    oldhook = shell('sha256sum ' + HOOK).stdout
    oldstate = shell('cat ' + BASE + '/component-state').stdout
    oldhost = shell('sha256sum ' + BASE + '/hostkeys/ed25519').stdout
    package('upgrade-failure', 'exit')
    failed = install(); assert failed.returncode != 0 and result()['phase'] == 'ROLLED_BACK', failed.stdout + failed.stderr
    assert shell('sha256sum ' + HOOK).stdout == oldhook and shell('cat ' + BASE + '/component-state').stdout == oldstate
    shell(BASE + '/releases/' + OLD + '/post-install-test.sh')
    assert oldhost == shell('sha256sum ' + BASE + '/hostkeys/ed25519').stdout
    ok('Failed upgrade restores previous hook/state and old SSH passes health checks with unchanged host identity')
    # Remove immutable failed candidate directory only after verified rollback.
    shell('rm -rf ' + BASE + '/releases/' + RELEASE + ' ' + BASE + '/transactions/txn-' + RELEASE + '-*')
    package('upgrade-timeout', 'hang')
    start = time.monotonic(); failed = install(); elapsed = time.monotonic() - start
    assert failed.returncode != 0 and 59 <= elapsed < 85 and result()['phase'] == 'ROLLED_BACK', (elapsed, failed.stdout, failed.stderr)
    shell(BASE + '/releases/' + OLD + '/post-install-test.sh')
    shell("! ps | grep '[s]leep 90'")
    ok('Hung TERM-ignoring test hits real 60-second deadline; process group is killed and previous SSH recovers')
    shell('rm -rf ' + BASE + '/releases/' + RELEASE + ' ' + BASE + '/transactions/txn-' + RELEASE + '-*')
    package('upgrade-success')
    installed = install(); assert installed.returncode == 0 and result()['phase'] == 'COMMITTED', installed.stdout + installed.stderr
    assert shell('cat ' + BASE + '/component-state').stdout == RELEASE + '\n' + str(COUNTER) + '\n'
    assert oldhost == shell('sha256sum ' + BASE + '/hostkeys/ed25519').stdout
    shell('test ! -e ' + BASE + '/pending')
    ok('Successful upgrade commits only after script passes, retains rollback snapshot and preserves host identity')
    package('downgrade', previous=True)
    assert install().returncode != 0
    ok('Committed SSH component counter blocks downgrade')
    assert original() == baseline
    ok('Success, failure and timeout preserve original Launcher and rcS')
    reset(); package('missing-production-ap', production_binding=True)
    failed = install(); assert failed.returncode != 0 and result()['phase'] == 'ROLLED_BACK', failed.stdout + failed.stderr
    no_listener(); ok('Missing production AP address fails health check and rolls back without wildcard listener')
    assert original() == baseline
    shell('test ! -e ' + HOOK + '; test ! -e ' + BASE + '/pending')
    text = '\n'.join('PASS ' + item for item in passed) + f'\nPASS {len(passed)} ARM64 transactional checks; isolated emulator only, no physical instrument.\n'
    (ROOT / 'dist/SSH增量回退测试结果.txt').write_text(text)
    print(text.splitlines()[-1], flush=True)


if __name__ == '__main__': main()
