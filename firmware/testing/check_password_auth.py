#!/usr/bin/env python3
"""Test password-enabled Dropbear in the isolated ARM64 chroot only.

Uses a random disposable password kept in process memory; never a device password.
Requires pexpect and the chroot prepared by prepare_chroot.py.
"""
import importlib.util
import os
from pathlib import Path
import secrets
import shlex
import subprocess
import time

import pexpect

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault('SSH703T_TEST_BUNDLE', str(ROOT / 'dist/JC_703T25_SSH_0.1.4_CANDIDATE.tar'))
spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('check_incremental_rollback.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def change_password(password):
    passwd_binary = os.environ.get('SSH703T_TEST_PASSWD_BINARY', '/bin/busybox')
    command = 'PATH=/bin:/usr/bin:/sbin:/usr/sbin /system/bin/chroot ' + d.REMOTE + ' ' + shlex.quote(passwd_binary) + ' passwd -a sha512 root'
    child = pexpect.spawn(str(d.ADB), ['-s', 'emulator-5556', 'shell', '-t', command], encoding='utf-8', timeout=15, echo=False)
    try:
        child.expect('New password:')
        child.sendline(password)
        child.expect('Retype password:')
        child.sendline(password)
        child.expect('[Pp]assword for root changed by root')
        child.expect(pexpect.EOF)
        child.close()
        assert child.exitstatus == 0
    except Exception:
        child.close(force=True)
        raise RuntimeError('Emulator passwd interaction failed (terminal output withheld)') from None


def password_login(args, password, succeeds):
    child = pexpect.spawn('ssh', args, encoding='utf-8', timeout=15, echo=False)
    try:
        child.expect('[Pp]assword:')
        child.sendline(password)
        child.expect(pexpect.EOF)
        output = child.before
        child.close()
        if succeeds:
            assert child.exitstatus == 0 and 'PASSWORD_OK0' in output
        else:
            assert child.exitstatus == 255 and 'Permission denied' in output
    except Exception:
        child.close(force=True)
        raise RuntimeError('Emulator password authentication assertion failed (output withheld)') from None


def main():
    assert d.adb('shell', 'getprop ro.kernel.qemu').stdout.strip() == '1'
    assert d.adb('shell', 'id -u').stdout.strip() == '0'
    assert d.adb('shell', 'uname -m').stdout.strip() == 'aarch64'
    d.adb('shell', 'setenforce 0')
    mounted = {line.split()[1] for line in d.adb('shell', 'cat /proc/mounts').stdout.splitlines()}
    r = d.REMOTE
    if r + '/dev' not in mounted:
        d.adb('shell', 'mount -t tmpfs -o mode=0755 tmpfs ' + r + '/dev; mkdir -p ' + r + '/dev/pts')
        for name, major, minor in (('null', 1, 3), ('zero', 1, 5), ('random', 1, 8), ('urandom', 1, 9), ('tty', 5, 0)):
            d.adb('shell', f'mknod {r}/dev/{name} c {major} {minor}; chmod 666 {r}/dev/{name}')
        d.adb('shell', 'mount -t devpts -o newinstance,ptmxmode=0666,mode=0620 devpts ' + r + '/dev/pts; ln -s pts/ptmx ' + r + '/dev/ptmx')
    if r + '/proc' not in mounted:
        d.adb('shell', 'mount --bind /proc ' + r + '/proc')
    # Other fixture tests intentionally leave these at 0775. Match the observed
    # instrument permissions so Dropbear's authorized-key ancestry check applies.
    d.shell('chmod 755 / /opt /etc/init.d')
    d.shell("mkdir -p /fixture; printf 'GT_G080-11\\n' > /fixture/lcdv")
    d.reset()
    baseline = d.original()
    d.package('password-auth')
    result = d.install()
    assert result.returncode == 0 and d.result()['phase'] == 'COMMITTED', result.stdout + result.stderr
    d.ok('Password-enabled component commits after original post-install checks')
    runtime = '/opt/703t-ssh/releases/' + d.RELEASE
    password = secrets.token_urlsafe(24)
    change_password(password)
    d.shell("test ! -L /etc/shadow; chmod 600 /etc/shadow; awk -F: '$1 == \"root\" { if (substr($2,1,3) == \"$6$\") found=1 } END { exit !found }' /etc/shadow")
    d.ok('Original BusyBox passwd writes SHA-512 crypt compatible with static musl Dropbear')
    public = d.shell(runtime + '/dropbearmulti dropbearkey -y -f /opt/703t-ssh/hostkeys/ed25519').stdout
    public = next(row for row in public.splitlines() if row.startswith('ssh-ed25519 '))
    port = d.adb('forward', 'tcp:0', 'tcp:2222').stdout.strip()
    known = d.OUT / 'password-test-known-hosts'
    known.write_text('[127.0.0.1]:' + port + ' ' + ' '.join(public.split()[:2]) + '\n')
    common = ['-F', '/dev/null', '-p', port, '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known), '-o', 'ConnectTimeout=5']
    try:
        keyargs = common + ['-i', str(ROOT / 'firmware/.ssh-access/id_ed25519'), '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', 'root@127.0.0.1', 'printf KEY_OK; id -u']
        result = subprocess.run(['ssh', *keyargs], capture_output=True, text=True, timeout=15)
        assert result.returncode == 0 and 'KEY_OK0' in result.stdout, result.stderr
        d.ok('Existing owner public key still authenticates root')
        passwordargs = common + ['-o', 'PubkeyAuthentication=no', '-o', 'PreferredAuthentications=password', '-o', 'NumberOfPasswordPrompts=1', 'root@127.0.0.1', 'printf PASSWORD_OK; id -u']
        password_login(passwordargs, password, True)
        d.ok('Correct password authenticates root and executes BusyBox shell')
        password_login(passwordargs, password + 'wrong', False)
        d.ok('Wrong password is rejected')
        result = subprocess.run(['ssh', *keyargs[:-2], 'nobody@127.0.0.1', 'true'], capture_output=True, text=True, timeout=15)
        assert result.returncode == 255 and 'Permission denied' in result.stderr
        d.ok('Non-root group account remains rejected')
        host = d.shell('sha256sum /opt/703t-ssh/hostkeys/ed25519').stdout
        d.shell('/etc/init.d/S97ssh703t stop')
        time.sleep(1)
        d.shell('/etc/init.d/S97ssh703t start; ' + runtime + '/post-install-test.sh')
        password_login(passwordargs, password, True)
        assert host == d.shell('sha256sum /opt/703t-ssh/hostkeys/ed25519').stdout
        assert baseline == d.original()
        d.ok('Password and host identity survive service restart; original Launcher/rcS unchanged')
    finally:
        d.adb('forward', '--remove', 'tcp:' + port, check=False)
        d.shell('/bin/busybox passwd -l root', check=False)
    print('PASS all password checks; isolated emulator only', flush=True)


if __name__ == '__main__':
    main()
