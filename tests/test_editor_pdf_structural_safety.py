"""Image bytes are data; executable PDF object graphs remain fail-closed."""
import io
import random
import unittest

import fitz
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, DecodedStreamObject, TextStringObject
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import backend


def synthetic_scanned_pdf():
    """Reproduce the 2 MB scanner-like ASCII85/Flate case without any PII."""
    rng = random.Random(20260925)
    stream = io.BytesIO()
    document = canvas.Canvas(stream, pagesize=A4, pageCompression=1, invariant=1)
    for number in range(3):
        pixels = Image.frombytes("L", (650, 850), rng.randbytes(650 * 850))
        document.drawString(35, 800, f"SYNTHETIC SCAN TEST {number + 1}")
        document.drawImage(ImageReader(pixels), 35, 65, width=525, height=690)
        document.showPage()
    document.save()
    return stream.getvalue()


def encoded_name(value, encoded):
    class EscapedName(NameObject):
        def write_to_stream(self, stream, encryption_key=None):
            stream.write(encoded)
    return EscapedName(value)


def writer_bytes(writer):
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class PdfStructuralSafetyTest(unittest.TestCase):
    def writer(self):
        writer = PdfWriter()
        writer.add_blank_page(width=A4[0], height=A4[1])
        return writer

    def test_reportlab_compressed_scan_with_incidental_js_bytes_is_accepted(self):
        data = synthetic_scanned_pdf()
        self.assertGreater(len(data), 2_000_000)
        self.assertIn(b"/JS", data)
        result = backend.inspect_editor_pdf(data)
        self.assertEqual(result["pageCount"], 3)
        self.assertFalse(result["flags"]["javascript"])
        with fitz.open(stream=data, filetype="pdf") as rendered:
            pixmap = rendered[0].get_pixmap(matrix=fitz.Matrix(0.2, 0.2))
            self.assertGreater(pixmap.width, 100)
            self.assertGreater(pixmap.height, 150)

    def test_image_stream_literals_are_not_dictionary_keys(self):
        writer = self.writer()
        image = DecodedStreamObject()
        marker = b"/JS /JavaScript /ByteRange /XFA "
        image.set_data((marker * 150)[:4096])
        image.update({NameObject("/Type"): NameObject("/XObject"), NameObject("/Subtype"): NameObject("/Image"),
                      NameObject("/Width"): NumberObject(64), NameObject("/Height"): NumberObject(64),
                      NameObject("/ColorSpace"): NameObject("/DeviceGray"), NameObject("/BitsPerComponent"): NumberObject(8)})
        writer.pages[0][NameObject("/Resources")] = DictionaryObject({NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): writer._add_object(image)})})
        content = DecodedStreamObject()
        content.set_data(b"q 100 0 0 100 30 30 cm /Im1 Do Q")
        writer.pages[0][NameObject("/Contents")] = writer._add_object(content)
        self.assertEqual(backend.inspect_editor_pdf(writer_bytes(writer))["pageCount"], 1)

    def test_direct_indirect_escaped_and_chained_script_actions_are_rejected(self):
        for kind in ("names", "escaped-value", "escaped-key", "next-chain", "stream-dictionary"):
            with self.subTest(kind=kind):
                writer = self.writer()
                if kind == "names":
                    writer.add_js("app.alert('synthetic')")
                else:
                    action = DictionaryObject({NameObject("/S"): NameObject("/JavaScript"), NameObject("/JS"): TextStringObject("synthetic()")})
                    if kind == "escaped-value":
                        action = DictionaryObject({NameObject("/S"): encoded_name("/JavaScript", b"/J#61vaScript")})
                    if kind == "escaped-key":
                        action = DictionaryObject({encoded_name("/JS", b"/J#53"): TextStringObject("synthetic()")})
                    if kind == "stream-dictionary":
                        action = DecodedStreamObject()
                        action.set_data(b"not-executed")
                        action[NameObject("/JS")] = TextStringObject("synthetic()")
                    if kind == "next-chain":
                        action = DictionaryObject({NameObject("/S"): NameObject("/GoTo"), NameObject("/Next"): ArrayObject([writer._add_object(action)])})
                    annotation = DictionaryObject({NameObject("/Subtype"): NameObject("/Link"), NameObject("/A"): writer._add_object(action)})
                    writer.pages[0][NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
                data = writer_bytes(writer)
                if kind in {"escaped-value", "escaped-key"}:
                    self.assertNotIn(b"/JavaScript", data)
                    self.assertNotIn(b"/JS", data)
                with self.assertRaisesRegex(ValueError, "javascript_not_supported"):
                    backend.inspect_editor_pdf(data)

    def test_compressed_object_stream_script_is_still_rejected(self):
        writer = self.writer()
        writer.add_js("app.alert('synthetic')")
        with fitz.open(stream=writer_bytes(writer), filetype="pdf") as source:
            compressed = source.tobytes(garbage=4, deflate=True, use_objstms=1)
        self.assertIn(b"/ObjStm", compressed)
        with self.assertRaisesRegex(ValueError, "javascript_not_supported"):
            backend.inspect_editor_pdf(compressed)

    def test_signature_and_xfa_dictionary_keys_remain_rejected_in_nested_objects(self):
        for key, error in (("/ByteRange", "digital_signature_not_supported"), ("/XFA", "xfa_not_supported")):
            with self.subTest(key=key):
                writer = self.writer()
                nested = DictionaryObject({NameObject(key): TextStringObject("synthetic")})
                writer._root_object[NameObject("/AcroForm")] = DictionaryObject({NameObject("/Fields"): ArrayObject([writer._add_object(nested)])})
                with self.assertRaisesRegex(ValueError, error):
                    backend.inspect_editor_pdf(writer_bytes(writer))

    def test_unresolvable_reachable_object_fails_closed(self):
        class BrokenReference:
            idnum = 42
            generation = 0
            def get_object(self):
                raise RuntimeError("synthetic malformed reference")
        with self.assertRaisesRegex(ValueError, "editor_pdf_corrupt:unresolved_object"):
            backend._inspect_editor_pdf_object_safety({"/Next": BrokenReference()})


if __name__ == "__main__":
    unittest.main()
