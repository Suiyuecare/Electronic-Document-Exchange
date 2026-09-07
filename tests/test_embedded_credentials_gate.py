import unittest
from tools.verify_no_embedded_credentials import detect


class EmbeddedCredentialsGateTests(unittest.TestCase):
    def test_private_credentials_are_detected_without_returning_values(self):
        self.assertEqual(detect(b"sk-" + b"proj-" + b"x" * 64), ["openai_private_key"])
        self.assertEqual(detect(b"sb_" + b"secret_" + b"a" * 40), ["supabase_private_key"])

    def test_public_keys_and_placeholder_names_are_not_private_credentials(self):
        self.assertEqual(detect(b"sb_publishable_" + b"x" * 64), [])
        self.assertEqual(detect(b"OPENAI_API_KEY=replace-me"), [])

    def test_private_pem_key_is_detected(self):
        self.assertEqual(detect(b"-----BEGIN " + b"PRIVATE KEY-----"), ["pem_private_key"])
