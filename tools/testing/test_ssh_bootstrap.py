#!/usr/bin/env python3
"""Offline checks for source publication's configurable bootstrap builder."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_ssh_bootstrap as bootstrap
import native_ota


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private, self.public = self.root / 'private.pem', self.root / 'public.pem'
        native_ota.openssl('genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072', '-out', self.private)
        self.public.write_bytes(native_ota.openssl('pkey', '-in', self.private, '-pubout'))
        self.rows = [(name, b'#!/bin/sh\nexit 0\n', 0o755) for name in sorted(bootstrap.ENTRYPOINTS)]
        self.rows += [('ssh703t/install.sh', b'#!/bin/sh\nRELEASE=fixture-4\nCOUNTER=4\nexit 0\n', 0o755),
                      ('ssh703t/payload/post-install-test.sh', b'#!/bin/sh\nexit 0\n', 0o755),
                      ('ssh703t/payload/rollback.sh', b'#!/bin/sh\nexit 0\n', 0o755),
                      ('ssh703t/payload/content', b'fixture content', 0o644)]

    def source(self, rows=None):
        path = self.root / 'component.tar'
        with tarfile.open(path, 'w:', format=tarfile.USTAR_FORMAT) as archive:
            for name, body, mode in self.rows if rows is None else rows:
                native_ota.add(archive, name, body, mode)
        Path(str(path) + '.sig').write_bytes(native_ota.openssl('dgst', '-sha256', '-sign', self.private, path))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def build(self, source, digest):
        return bootstrap.build(source, digest, self.root / 'native.tar', 'fixture-native-4', self.public, self.private)

    def test_payload_preserved_signed_and_versioned(self):
        result = self.build(*self.source())
        self.assertEqual(result['component_release'], 'fixture-4')
        self.assertEqual(result['component_counter'], 4)
        self.assertFalse(result['physical_instrument_tested'])
        with tarfile.open(self.root / 'native.tar') as archive:
            rows = {m.name: archive.extractfile(m).read() for m in archive}
        for name, body, mode in self.rows:
            if name not in bootstrap.ENTRYPOINTS:
                self.assertEqual(rows[name], body)
        wrappers = [rows[name] for name in bootstrap.ENTRYPOINTS]
        self.assertTrue(all(w == wrappers[0] for w in wrappers))
        self.assertNotIn(b'__INSTALL_SHA__', wrappers[0])
        self.assertIn(hashlib.sha256(rows['ssh703t/install.sh']).hexdigest().encode(), wrappers[0])
        manifest = json.loads(rows[native_ota.META])
        self.assertEqual(manifest['release'], 'fixture-native-4')
        self.assertEqual(manifest['kind'], 'incremental')
        for record in manifest['files']:
            self.assertEqual(record['sha256'], hashlib.sha256(rows[record['path']]).hexdigest())
        meta, sig = self.root / 'manifest.json', self.root / 'manifest.sig'
        meta.write_bytes(rows[native_ota.META]); sig.write_bytes(rows[native_ota.SIG])
        native_ota.openssl('dgst', '-sha256', '-verify', self.public, '-signature', sig, meta)

    def test_changed_source_rejected(self):
        source, digest = self.source()
        source.write_bytes(source.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'Reviewed source changed'):
            self.build(source, digest)

    def test_bad_signature_rejected(self):
        source, digest = self.source()
        Path(str(source) + '.sig').write_bytes(b'invalid')
        with self.assertRaises(subprocess.CalledProcessError):
            self.build(source, digest)

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.build(*self.source(self.rows + [self.rows[0]]))

    def test_unexpected_payload_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected component path'):
            self.build(*self.source(self.rows + [('Launcher', b'bad', 0o755)]))

    def test_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unsafe TAR path'):
            self.build(*self.source(self.rows + [('../outside', b'bad', 0o755)]))

    def test_existing_output_rejected(self):
        source = self.source()
        self.build(*source)
        previous = (self.root / 'native.tar').read_bytes()
        with self.assertRaisesRegex(ValueError, 'new .tar'):
            self.build(*source)
        self.assertEqual((self.root / 'native.tar').read_bytes(), previous)


if __name__ == '__main__':
    unittest.main(verbosity=2)
