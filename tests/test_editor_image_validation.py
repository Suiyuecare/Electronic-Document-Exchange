import io
import unittest

from PIL import Image

import backend


class EditorImageValidationTest(unittest.TestCase):
    def image_bytes(self, image_format="PNG"):
        output = io.BytesIO()
        Image.new("RGB", (24, 16), "orange").save(output, format=image_format)
        return output.getvalue()

    def test_valid_png_and_jpeg(self):
        for image_format, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
            with self.subTest(image_format=image_format):
                result = backend.inspect_editor_image(self.image_bytes(image_format), mime)
                self.assertEqual((result["widthPx"], result["heightPx"]), (24, 16))
                self.assertEqual(result["format"], image_format)

    def test_bad_png_checksum_returns_controlled_validation_error(self):
        damaged = bytearray(self.image_bytes())
        chunk_type = damaged.index(b"IDAT")
        chunk_length = int.from_bytes(damaged[chunk_type - 4:chunk_type], "big")
        damaged[chunk_type + 4 + chunk_length] ^= 1
        with self.assertRaises(SyntaxError):
            with Image.open(io.BytesIO(damaged)) as image:
                image.verify()
        with self.assertRaisesRegex(ValueError, "^editor_image_invalid$"):
            backend.inspect_editor_image(bytes(damaged), "image/png")

    def test_truncated_png_returns_controlled_validation_error(self):
        with self.assertRaisesRegex(ValueError, "^editor_image_invalid$"):
            backend.inspect_editor_image(self.image_bytes()[:45], "image/png")

    def test_declared_mime_must_match_actual_format(self):
        with self.assertRaisesRegex(ValueError, "^editor_image_invalid$"):
            backend.inspect_editor_image(self.image_bytes(), "image/jpeg")

    def test_unsupported_type_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^editor_image_type_not_supported$"):
            backend.inspect_editor_image(b"<svg/>", "image/svg+xml")


if __name__ == "__main__":
    unittest.main()
