"""Exact original scan policy tests, using metadata and isolated raster fixtures."""
import hashlib
import io
import sqlite3
import unittest
from pathlib import Path
from unittest import mock
from PIL import Image
import backend
import seal_policy
import seal_scan_exceptions as scan
from tools.seal_scan_exception_forward import source_sql, shared_sql, SOURCE, SHARED


def approved_row(values):
    digest, company, seal_id, category, size, w, h, mw, mh, page = values
    return {"seal_id": seal_id, "file_hash": digest, "pixel_width": w, "pixel_height": h,
            "source_aspect_ratio": w / h, "render_width_mm": mw, "render_height_mm": mh,
            "dimension_policy_version": scan.POLICY, "dimension_validated": True}


class ApprovedOriginalScanTest(unittest.TestCase):
    def test_all_22_versions_keep_exact_native_geometry(self):
        self.assertEqual(len(scan._ROWS), 22)
        self.assertEqual(len({r[0] for r in scan._ROWS}), 22)
        for values in scan._ROWS:
            row = approved_row(values)
            self.assertTrue(backend.company_seal_file_dimension_is_valid(row, values[4]))
            self.assertTrue(seal_policy.category_policy_valid(values[3], values[4], row))
            profile = backend.company_seal_file_dimension_profile(values[4], row, current=True)
            self.assertEqual((profile["width_mm"],profile["height_mm"]),values[7:9])
            self.assertAlmostEqual(profile["width_mm"]/profile["height_mm"],values[5]/values[6])
            self.assertEqual(profile["calibration_dpi"],200)
            self.assertEqual(backend.canonical_company_seal_dimensions_pt(values[4],render_width_mm=values[7],render_height_mm=values[8],allow_unspecified=True,dimension_policy_version=scan.POLICY),(profile["width_pt"],profile["height_pt"]))

    def test_changed_hash_slot_category_size_geometry_or_policy_is_rejected(self):
        values = scan._ROWS[0]
        row = approved_row(values)
        for key,value in (("file_hash","f"*64),("seal_id","other-slot"),("pixel_width",236),
                          ("source_aspect_ratio",1), ("render_width_mm",30),
                          ("render_height_mm",float("nan")), ("dimension_validated",False),
                          ("dimension_policy_version","invented-policy")):
            with self.subTest(key=key):
                self.assertFalse(backend.company_seal_file_dimension_is_valid({**row,key:value},values[4]))
        self.assertFalse(seal_policy.category_policy_valid("general_seal",values[4],row))
        self.assertFalse(backend.company_seal_file_dimension_is_valid(row,"small_seal"))

    def test_attestation_types_are_not_truthy_or_integer_coerced(self):
        r=scan._ROWS[0]; row=approved_row(r)
        for key,value in (("dimension_validated","false"),("dimension_validated",2),
                          ("pixel_width",235.9),("pixel_width","235"),("pixel_width",True),
                          ("source_aspect_ratio",str(r[5]/r[6])),("render_width_mm",True),
                          ("render_height_mm",10**1000)):
            with self.subTest(key=key,value=type(value).__name__):
                self.assertIsNone(scan.file_entry({**row,key:value},r[4]))
        self.assertTrue(scan.file_entry({**row,"dimension_validated":1},r[4]))

    def test_unknown_200dpi_raster_does_not_get_exception(self):
        buf=io.BytesIO()
        Image.new("RGBA",(235,235),(190,0,0,255)).save(buf,format="PNG")
        with self.assertRaisesRegex(ValueError,"resolution_too_low"):
            backend.validate_seal_file_upload("synthetic.png","image/png",buf.getvalue(),"large_seal",30,30,"establishment_seal")
        self.assertEqual(backend.EDOC_SEAL_CALIBRATION_DPI,250)

    def test_known_hash_cannot_be_bound_to_wrong_company_or_resized(self):
        r=scan._ROWS[0]
        seal={"id":r[2],"company_id":r[1],"seal_category":r[3],"seal_size_type":r[4]}
        self.assertTrue(scan.upload_match(seal,r[0],r[5],r[6],r[7],r[8]))
        self.assertIsNone(scan.upload_match({**seal,"company_id":"wrong"},r[0],r[5],r[6],r[7],r[8]))
        for width in (30,float("nan"),float("inf"),None):
            with self.assertRaises(ValueError):
                scan.upload_match(seal,r[0],r[5],r[6],width,r[8])

    def test_sqlite_udf_has_same_strict_metadata_binding(self):
        conn=sqlite3.connect(":memory:")
        backend.register_sqlite_functions(conn)
        r=scan._ROWS[0]
        args=(r[2],r[1],r[3],r[4],r[0],r[5],r[6],r[5]/r[6],r[7],r[8],scan.POLICY,True)
        query="SELECT edoc_approved_original_scan_matches("+",".join("?" for _ in args)+")"
        self.assertEqual(conn.execute(query,args).fetchone()[0],1)
        self.assertEqual(conn.execute(query,(*args[:4],"0"*64,*args[5:])).fetchone()[0],0)
        conn.close()

    def test_forwards_are_deterministic_and_generic_dpi_helper_not_redefined(self):
        root=Path(__file__).resolve().parents[1]
        source=source_sql()
        self.assertEqual((root/"supabase/migrations"/SOURCE).read_text(),source)
        self.assertEqual((root/"supabase/shared-project-migrations"/SHARED).read_text(),shared_sql(source))
        self.assertNotIn("create or replace function public.edoc_company_seal_dimensions_are_valid(",source.lower())
        self.assertNotIn("insert into public.company_seals",source.lower())

    def test_local_prepared_originals_are_exact_and_decodable_when_available(self):
        folder=Path(__file__).resolve().parents[2]/"artifacts/seal-registration-20261013/prepared"
        if not folder.exists(): self.skipTest("private supplied originals unavailable in this isolated environment")
        for values in scan._ROWS:
            matches=[p for p in folder.glob("*.png") if hashlib.sha256(p.read_bytes()).hexdigest()==values[0]]
            self.assertEqual(len(matches),1)
            data=matches[0].read_bytes()
            seal={"id":values[2],"company_id":values[1],"seal_category":values[3],"seal_size_type":values[4]}
            result=backend.validate_seal_file_upload(matches[0].name,"image/png",data,values[4],values[7],values[8],values[3],seal)
            self.assertEqual(result["dimension_policy_version"],scan.POLICY)
            self.assertEqual((result["pixel_width"],result["pixel_height"]),values[5:7])


if __name__ == "__main__": unittest.main()
