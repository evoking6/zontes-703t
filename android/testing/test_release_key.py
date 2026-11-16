import hashlib
import pathlib
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from release_key import ensure_release_key


class ReleaseIdentityTests(unittest.TestCase):
    def test_repeated_build_reuses_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = ensure_release_key(tmp)
            before = hashlib.sha256(first['private'].read_bytes()).digest()
            second = ensure_release_key(tmp)
            self.assertEqual(first['key_id'], second['key_id'])
            self.assertEqual(before, hashlib.sha256(second['private'].read_bytes()).digest())
            self.assertEqual(second['private'].stat().st_mode & 0o777, 0o600)

    def test_public_only_checkout_does_not_rotate_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            identity = ensure_release_key(tmp)
            identity['private'].unlink()
            rebuilt = ensure_release_key(tmp)
            self.assertIsNone(rebuilt['private'])
            self.assertEqual(identity['key_id'], rebuilt['key_id'])
            self.assertFalse((pathlib.Path(tmp) / '.firmware-signing/release-private.pem').exists())

    def test_mismatched_existing_key_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            identity = ensure_release_key(one)
            other = ensure_release_key(two)
            shutil.copyfile(other['public'], identity['public'])
            with self.assertRaisesRegex(RuntimeError, '不匹配'):
                ensure_release_key(one)


if __name__ == '__main__': unittest.main()
