#!/usr/bin/env python3
"""Offline package/production Java TCP integration tests. Binds loopback only."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tarfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'android/testing/generated/native'
JAVA = Path(os.environ['JAVA_HOME']) / 'bin' if os.environ.get('JAVA_HOME') else Path('/Library/Java/JavaVirtualMachines/jdk-17.jdk/Contents/Home/bin')
spec = importlib.util.spec_from_file_location('native_ota', ROOT / 'tools/native_ota.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
VERSION = 'JC_703T25_V02.26.02.02.60'


def frame(op, body=b''):
    return struct.pack('>H', len(body) + 1) + bytes([op]) + body + b'JC'


def exact(sock, count):
    data = b''
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise EOFError('client disconnected')
        data += chunk
    return data


def receive(sock):
    size, = struct.unpack('>H', exact(sock, 2))
    if not 1 <= size <= 5000:
        raise AssertionError('bad frame length')
    data = exact(sock, size)
    if exact(sock, 2) != b'JC':
        raise AssertionError('bad trailer')
    return data[0], data[1:]


def version_response(version=VERSION):
    text = version.encode()
    return frame(1, b'JC' + b'\0' * (64 - len(text)) + text)


def emit(sock, data, fragmented=False):
    if fragmented:
        for byte in data:
            sock.sendall(bytes([byte]))
    else:
        sock.sendall(data)


class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True, exist_ok=True)
        cls.key, cls.pub = OUT / 'TEST-ONLY-private.pem', OUT / 'TEST-ONLY-public.pem'
        if not cls.key.exists():
            native.openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', cls.key)
            cls.key.chmod(0o600)
        cls.pub.write_bytes(native.openssl('pkey', '-in', cls.key, '-pubout'))
        raw = OUT / 'TEST-ONLY-input.tar'
        with tarfile.open(raw, 'w:', format=tarfile.USTAR_FORMAT) as tar:
            for name, data, mode in [('updateFile_GT.sh', b'#!/bin/sh\nexit 0\n', 0o755), ('updateFile_HW.sh', b'#!/bin/sh\nexit 0\n', 0o755),
                                     ('test.sh', b'#!/bin/sh\nexit 0\n', 0o755), ('rollback.sh', b'#!/bin/sh\nexit 0\n', 0o755), ('payload.dat', bytes(range(256)) * 40, 0o644)]:
                native.add(tar, name, data, mode)
        cls.raw, cls.full, cls.delta = raw, OUT / 'TEST-ONLY-full.tar', OUT / 'TEST-ONLY-delta.tar'
        for file, kind in [(cls.full, 'full'), (cls.delta, 'incremental')]:
            file.unlink(missing_ok=True)
            native.build(raw, file, cls.key, kind, 'TEST-ONLY-1', VERSION if kind == 'incremental' else '', 'test.sh' if kind == 'incremental' else '', 'rollback.sh' if kind == 'incremental' else '')
        classes = OUT / 'classes'
        classes.mkdir(exist_ok=True)
        subprocess.run([str(JAVA / 'javac'), '-encoding', 'UTF-8', '--release', '8', '-d', str(classes), *map(str, sorted((ROOT / 'android/src/cn/local/instrument703t/core').glob('*.java'))), str(ROOT / 'android/testing/NativeChecks.java')], check=True)
        cls.classes = classes

    def java(self, path, mode='verify', port=None):
        return subprocess.run([str(JAVA / 'java'), '-cp', str(self.classes), 'NativeChecks', mode, str(path), str(self.pub), *([str(port)] if port else [])], capture_output=True, text=True, timeout=35)

    def rewrite(self, name, change, resign=False):
        target = OUT / ('TEST-ONLY-' + name + '.tar')
        with tarfile.open(self.delta) as tar:
            rows = [(m.name, tar.extractfile(m).read(), m.mode) for m in tar]
        rows = change(rows)
        if resign:
            meta = next(data for name, data, mode in rows if name == native.META)
            path = OUT / 'TEST-ONLY-resign.json'
            path.write_bytes(meta)
            sig = native.openssl('dgst', '-sha256', '-sign', self.key, path)
            rows = [(n, sig if n == native.SIG else d, m) for n, d, m in rows]
        with tarfile.open(target, 'w:', format=tarfile.USTAR_FORMAT) as tar:
            for n, data, mode in rows:
                native.add(tar, n, data, mode)
        return target

    def mutate_manifest(self, name, function):
        def mutate(rows):
            result = []
            for path, data, mode in rows:
                if path == native.META:
                    manifest = json.loads(data)
                    function(manifest)
                    data = json.dumps(manifest).encode()
                result.append((path, data, mode))
            return result
        return self.rewrite(name, mutate, True)

    def rejected(self, path):
        result = self.java(path)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_01_factory_full_exact_hash(self):
        factory = Path(os.environ.get('SSH703T_FACTORY_ARCHIVE', str(ROOT / 'JC_703T25_V02.26.02.02.60.tar')))
        if not factory.is_file():
            self.skipTest('Optional owner-supplied factory archive is not redistributed')
        self.assertIn('VERIFIED full 110', self.java(factory).stdout)

    def test_02_signed_full(self):
        self.assertIn('VERIFIED full', self.java(self.full).stdout)

    def test_03_signed_incremental(self):
        self.assertIn('VERIFIED incremental', self.java(self.delta).stdout)

    def test_04_unsigned_rejected(self):
        self.rejected(self.raw)

    def test_05_tampered_payload(self):
        self.rejected(self.rewrite('tampered', lambda rows: [(n, d + b'x' if n == 'payload.dat' else d, m) for n, d, m in rows]))

    def test_06_signature_tamper(self):
        self.rejected(self.rewrite('signature', lambda rows: [(n, bytes([d[0] ^ 1]) + d[1:] if n == native.SIG else d, m) for n, d, m in rows]))

    def test_07_traversal(self):
        self.rejected(self.rewrite('traversal', lambda rows: rows + [('../escape', b'x', 0o644)]))

    def test_08_duplicate(self):
        self.rejected(self.rewrite('duplicate', lambda rows: rows + [rows[0]]))

    def test_09_unlisted(self):
        self.rejected(self.rewrite('unlisted', lambda rows: rows + [('extra', b'x', 0o644)]))

    def test_10_wrong_model(self):
        self.rejected(self.mutate_manifest('model', lambda m: m.update(model='other')))

    def test_11_incremental_needs_base(self):
        self.rejected(self.mutate_manifest('base', lambda m: m.update(base_version='')))

    def test_12_incremental_needs_test(self):
        self.rejected(self.mutate_manifest('test', lambda m: m.update(test_script='missing.sh')))

    def test_13_incremental_needs_rollback(self):
        self.rejected(self.mutate_manifest('rollback', lambda m: m.update(rollback_script='missing.sh')))

    def test_14_wrong_numeric_type(self):
        self.rejected(self.mutate_manifest('bool-size', lambda m: m['files'][0].update(size=True)))

    def test_15_truncated(self):
        path = OUT / 'TEST-ONLY-truncated.tar'
        path.write_bytes(self.delta.read_bytes()[:2048])
        self.rejected(path)

    def test_16_symlink(self):
        path = OUT / 'TEST-ONLY-symlink.tar'
        with tarfile.open(path, 'w:', format=tarfile.USTAR_FORMAT) as tar:
            item = tarfile.TarInfo('link'); item.type = tarfile.SYMTYPE; item.linkname = '/etc'; tar.addfile(item)
        self.rejected(path)

    def transfer(self, scenario='ok', pack=None, mode='update', fragmented=False):
        pack = pack or self.delta
        payload = pack.read_bytes()
        server = socket.socket(); server.bind(('127.0.0.1', 0)); server.listen(1); server.settimeout(30)
        port = server.getsockname()[1]
        outcome = {'install': False, 'error': None, 'bytes': 0}

        def serve():
            try:
                with server.accept()[0] as sock:
                    sock.settimeout(25)
                    self.assertEqual(receive(sock), (0, b''))
                    reply = version_response('JC_368G25_V02.26.02.02.60' if scenario == 'model' else 'JC_703T25_V02.25.01.01.01' if scenario == 'base' else VERSION)
                    if scenario == 'bad-tail': reply = reply[:-2] + b'XX'
                    if scenario == 'bad-length': reply = b'\xff\xff'
                    emit(sock, reply, fragmented)
                    op, meta = receive(sock)
                    self.assertEqual(op, 2); self.assertEqual(len(meta), 38)
                    size, name_len = struct.unpack('>IH', meta[:6])
                    self.assertEqual(size, len(payload)); self.assertEqual(meta[6:6 + name_len], b'JC_703T25_OTA.tar'); self.assertEqual(meta[6 + name_len:], b'\0' * (32 - name_len))
                    emit(sock, frame(2, struct.pack('>H', 500 if scenario == 'reject' else 200)), fragmented)
                    if scenario == 'reject': return
                    if scenario == 'early':
                        sock.sendall(frame(4)); time.sleep(.02)
                    count, seq, old_percent = 0, 0, -1
                    digest = hashlib.sha256()
                    while count < size:
                        op, data = receive(sock)
                        if op == 5: outcome['install'] = True; raise AssertionError('early install')
                        self.assertEqual(op, 3); self.assertEqual(int.from_bytes(data[1:4], 'big'), seq)
                        block = data[4:]; expected = min(4096, size - count)
                        self.assertEqual(len(block), expected); self.assertEqual(data[0], int(count + expected == size))
                        digest.update(block); count += len(block); seq += 1; outcome['bytes'] = count
                        if scenario == 'disconnect': return
                        if scenario == 'packet-error': sock.sendall(frame(3, b'\x01\xf4\0\0\0')); continue
                        if scenario == 'progress-over': sock.sendall(frame(6, b'\x65')); continue
                        if scenario == 'backwards': sock.sendall(frame(6, b'\x32') + frame(6, b'\x20')); continue
                        progress = count * 100 // size
                        if progress != old_percent:
                            emit(sock, frame(6, bytes([progress])), fragmented)
                            old_percent = progress
                    self.assertEqual(digest.hexdigest(), hashlib.sha256(payload).hexdigest())
                    if scenario == 'no-finish':
                        time.sleep(17)
                    else:
                        sock.sendall(frame(4))
                    op, data = receive(sock); outcome['install'] = op == 5
                    self.assertEqual((op, data), (5, b''))
                    if scenario == 'delayed-install-close':
                        sock.settimeout(.25)
                        try:
                            pending = sock.recv(1)
                        except socket.timeout:
                            pending = None
                        self.assertIsNone(pending, 'Client closed before receiver processed installation confirmation')
            except (EOFError, BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                outcome['error'] = repr(error)
            finally:
                server.close()
        thread = threading.Thread(target=serve, daemon=True); thread.start()
        result = self.java(pack, mode, port); thread.join(28)
        self.assertFalse(thread.is_alive(), 'mock receiver hung')
        self.assertIsNone(outcome['error'], outcome)
        if scenario in ('ok', 'delayed-install-close') and mode == 'update':
            self.assertEqual(result.returncode, 0, result.stderr); self.assertTrue(outcome['install']); self.assertEqual(outcome['bytes'], len(payload)); self.assertIn('INSTALL_REQUEST_SENT', result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout); self.assertFalse(outcome['install']); self.assertNotIn('INSTALL_CALLBACK', result.stdout)
        return result

    def test_20_incremental_tcp(self): self.transfer()
    def test_21_full_tcp(self): self.transfer(pack=self.full)
    def test_22_fragmented_replies(self): self.transfer(fragmented=True)
    def test_23_mismatched_device(self): self.transfer('model')
    def test_24_mismatched_base(self): self.transfer('base')
    def test_25_device_reject(self): self.transfer('reject')
    def test_26_response_tail(self): self.transfer('bad-tail')
    def test_27_response_length(self): self.transfer('bad-length')
    def test_28_mid_transfer_disconnect(self): self.transfer('disconnect')
    def test_29_packet_failure(self): self.transfer('packet-error')
    def test_30_progress_bounds(self): self.transfer('progress-over')
    def test_31_progress_regression(self): self.transfer('backwards')
    def test_32_cancel_never_installs(self): self.transfer(mode='cancel')
    def test_33_no_receive_finish_never_installs(self): self.transfer('no-finish')

    def test_34_exact_4096_multiple(self):
        path = OUT / 'TEST-ONLY-aligned.tar'
        data = self.full.read_bytes()
        path.write_bytes(data + b'\0' * (-len(data) % 4096))
        self.transfer(pack=path)

    def test_35_metadata_is_not_an_install_result(self):
        result = self.transfer()
        self.assertNotIn('COMMITTED', result.stdout)

    def test_37_receiver_closes_install_session(self):
        self.transfer('delayed-install-close')

    def test_36_large_stream(self):
        raw, output = OUT / 'TEST-ONLY-large-input.tar', OUT / 'TEST-ONLY-large.tar'
        with tarfile.open(raw, 'w:', format=tarfile.USTAR_FORMAT) as tar:
            native.add(tar, 'payload.dat', b'abcdef01' * (1024 * 1024))
        output.unlink(missing_ok=True)
        native.build(raw, output, self.key, 'full', 'TEST-ONLY-large')
        self.transfer(pack=output)


if __name__ == '__main__':
    unittest.main(verbosity=2)
