"""Two physical letter seals use distinct, immutable assets; no live systems."""
import base64
import io
import unittest
from unittest import mock

from PIL import Image
from pypdf import PdfReader

import backend
from tests import test_official_document_workflow as workflow_fixture
from tests import test_compose_resilience_frontend as frontend_fixture


class ComposeMultiSealFrontendTest(unittest.TestCase):
    run_js = frontend_fixture.ComposeResilienceFrontendTest.run_js

    EXISTING_SETUP = '''
      const calls=[],composeRequestScope=()=>"A";let composeOfficialContentRevision=3;
      const composeCompanyForOfficialApplication=()=>({id:"CO"}),activeUnit=()=>"fixture",officialComposeMetadata=()=>({}),officialSealHasCurrentFile=()=>true;
      const companySealFixedGeometry=seal=>({widthPt:seal.width,heightPt:seal.height,sealSizeType:seal.seal_size_type});
      const seals=[{id:"L",seal_category:"general_seal",seal_size_type:"large_seal",width:99.21,height:99.21},{id:"S",seal_category:"establishment_seal",seal_size_type:"small_seal",width:56.69,height:56.69},{id:"N",seal_category:"bank_seal",seal_size_type:"large_seal",width:90,height:90}];
      const existing=[{id:"POS-L",seal_id:"L",width:85.04,height:85.04,locked_seal_file_id:"FILE-L-OLD",locked_seal_sha256:"old-large-hash",locked_render_width_pt:85.04,locked_render_height_pt:85.04,locked_dimension_policy_version:"fixed-v1"}];
      const backendRequest=async(path,options)=>{calls.push({path,payload:options?JSON.parse(options.body):null});if(!options)return path.includes("/companies/")?seals:{stamp_request:{stamp_positions:existing}};return{id:"OD-SAVED",dispatch_no:"TEST",content_revision:4,stamp_request:{stamp_positions:JSON.parse(options.body).stamp_positions}}};
      global.document={querySelector:()=>({files:[]})};global.window={confirm:()=>true};
      const data={outputMode:"physical",largeSealType:"一般章",smallSealType:"公司設立章",approvalFlowNodes:[],sealPlacements:{large:{page:1,x:60,y:70},small:{page:1,x:80,y:85}}};
    '''

    def test_existing_single_seal_addition_fetches_identity_and_preserves_old_calibrated_version(self):
        result = self.run_js(["createOfficialApplicationFromCompose", "composeSealCategory"], self.EXISTING_SETUP, '''await createOfficialApplicationFromCompose({officialDocumentId:"OD-SAVED"},data,{submit:false});console.log(JSON.stringify(calls[calls.length-1].payload));''')
        positions = result["stamp_positions"]
        self.assertEqual(positions[0]["id"], "POS-L")
        self.assertEqual(positions[0]["locked_seal_file_id"], "FILE-L-OLD")
        self.assertEqual(positions[0]["width"], 85.04, "must not follow the new 35 mm current file")
        self.assertNotIn("id", positions[1])
        self.assertNotIn("rebind_current", positions[1], "a genuine addition needs no identity replacement")
        self.assertEqual(result["expected_content_revision"], 3)

    def test_removing_large_keeps_small_identity_even_when_order_changes(self):
        body = '''existing.push({id:"POS-S",seal_id:"S",width:56.69,height:56.69,locked_seal_file_id:"FILE-S",locked_seal_sha256:"small-hash",locked_render_width_pt:56.69,locked_render_height_pt:56.69,locked_dimension_policy_version:"fixed-v1"});data.largeSealType="無";await createOfficialApplicationFromCompose({officialDocumentId:"OD-SAVED",officialStampPositions:existing},data,{submit:false});console.log(JSON.stringify(calls[calls.length-1].payload));'''
        result = self.run_js(["createOfficialApplicationFromCompose", "composeSealCategory"], self.EXISTING_SETUP, body)
        self.assertEqual(result["seal_id"], "S")
        self.assertEqual(len(result["stamp_positions"]), 1)
        self.assertEqual(result["stamp_positions"][0]["id"], "POS-S")
        self.assertEqual(result["stamp_positions"][0]["order_index"], 1)

    def test_replacement_requires_explicit_confirmation_before_any_patch(self):
        body = '''data.largeSealType="銀行印鑑章";data.smallSealType="無";window.confirm=()=>false;let error="";try{await createOfficialApplicationFromCompose({officialDocumentId:"OD-SAVED",officialStampPositions:existing},data,{submit:false})}catch(e){error=e.message}console.log(JSON.stringify({mutations:calls.filter(c=>c.payload).length,error}));'''
        result = self.run_js(["createOfficialApplicationFromCompose", "composeSealCategory"], self.EXISTING_SETUP, body)
        self.assertEqual(result["mutations"], 0)
        self.assertIn("已取消印章變更", result["error"])

    def test_confirmed_replacement_carries_rebind_intent_without_old_identity(self):
        body = '''data.largeSealType="銀行印鑑章";data.smallSealType="無";await createOfficialApplicationFromCompose({officialDocumentId:"OD-SAVED",officialStampPositions:existing},data,{submit:false});console.log(JSON.stringify(calls[calls.length-1].payload.stamp_positions));'''
        result = self.run_js(["createOfficialApplicationFromCompose", "composeSealCategory"], self.EXISTING_SETUP, body)
        self.assertEqual(result[0]["seal_id"], "N")
        self.assertTrue(result[0]["rebind_current"])
        self.assertNotIn("id", result[0])
    def test_both_selected_seals_keep_own_geometry_position_and_one_directory_fetch(self):
        setup = '''
          const calls=[],composeRequestScope=()=>"A";let composeOfficialContentRevision=null;
          const composeCompanyForOfficialApplication=()=>({id:"CO"}),activeUnit=()=>"fixture",
            ensureComposeDraftRequestId=()=>"OD-TEST",officialComposeMetadata=()=>({}),officialSealHasCurrentFile=()=>true;
          const companySealFixedGeometry=seal=>({widthPt:seal.width,heightPt:seal.height,sealSizeType:seal.seal_size_type});
          const seals=[{id:"L",seal_category:"general_seal",seal_size_type:"large_seal",width:85.04,height:85.04},{id:"S",seal_category:"establishment_seal",seal_size_type:"small_seal",width:56.69,height:56.69}];
          const backendRequest=async(path,options)=>{calls.push({path,payload:options?JSON.parse(options.body):null});return options?{id:"OD-TEST",dispatch_no:"TEST",content_revision:1}:seals};
          global.document={querySelector:()=>({files:[]})};
          const data={outputMode:"physical",largeSealType:"一般章",smallSealType:"公司設立章",approvalFlowNodes:[],sealPlacements:{large:{page:1,x:60,y:70},small:{page:2,x:80,y:85}}};
        '''
        result = self.run_js(["createOfficialApplicationFromCompose", "composeSealCategory"], setup, '''await createOfficialApplicationFromCompose({},data,{submit:false});console.log(JSON.stringify({calls}));''')
        self.assertEqual(len(result["calls"]), 2)
        payload = result["calls"][1]["payload"]
        self.assertEqual(payload["seal_id"], "L")
        self.assertEqual([p["seal_id"] for p in payload["stamp_positions"]], ["L", "S"])
        self.assertEqual([p["page"] for p in payload["stamp_positions"]], [1, 2])
        self.assertEqual([p["width"] for p in payload["stamp_positions"]], [85.04, 56.69])
        self.assertEqual([p["order_index"] for p in payload["stamp_positions"]], [1, 2])


class ComposeMultiSealBackendTest(unittest.TestCase):
    def setUp(self):
        self.fixture = workflow_fixture.OfficialDocumentWorkflowTestCase()
        self.fixture.setUp()
        self.conn = self.fixture.conn
        self.session = self.fixture.login_session("sales-assistant@suiyuecare.com")
        self.large = self.fixture.seed_seal_id()
        self.small = self.conn.execute("SELECT id FROM company_seals WHERE company_id='CO-001' AND seal_category='establishment_seal' AND seal_size_type='small_seal'").fetchone()[0]
        self.upload_small((0, 0, 200, 255))

    def tearDown(self):
        self.fixture.tearDown()

    def upload_small(self, color):
        image = Image.new("RGBA", (400, 400), color)
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        return backend.upload_company_seal_file(self.conn, self.small, {
            "file_name": "synthetic-small.png", "file_mime_type": "image/png",
            "content_base64": base64.b64encode(stream.getvalue()).decode("ascii"), "actor": "unit-test",
        })

    def create(self, *, submit=True, only_large=False):
        positions = []
        for index, seal_id in enumerate((self.large, self.small)):
            seal = backend.company_seal_row(self.conn, seal_id)
            profile = backend.company_seal_file_dimension_profile(seal["seal_size_type"], seal["current_file"])
            positions.append({"seal_id": seal_id, "page": 1, "x": 300 + index * 110, "y": 100,
                              "width": profile["width_pt"], "height": profile["height_pt"], "order_index": index + 1})
        return backend.create_official_document(self.conn, {
            "source_type": "blank_editor", "company_id": "CO-001", "seal_id": self.large,
            "document_type": "outgoing_official_document", "output_mode": "physical",
            "title": "兩枚合成印章測試", "subject": "檢送兩枚合成印章測試資料，請查照。", "description": "僅限去識別化測試，不寄送。",
            "recipient": "測試機關", "document_category": "主管機關 申請或回覆文件（與 費用、法令無關）",
            "stamp_positions": positions[:1] if only_large else positions, "submit": submit,
        }, self.session)

    def test_saved_single_draft_addition_then_removal_preserves_surviving_server_identities(self):
        detail = self.create(submit=False, only_large=True)
        original = backend.official_document_stamp_request(self.conn, detail["id"])["stamp_positions"][0]
        seal = backend.company_seal_row(self.conn, self.small)
        profile = backend.company_seal_file_dimension_profile(seal["seal_size_type"], seal["current_file"])
        new_position = {"seal_id": self.small, "page": 1, "x": 410, "y": 100, "width": profile["width_pt"], "height": profile["height_pt"], "order_index": 2}
        edited = backend.update_official_document_correction(self.conn, detail["id"], {
            "stamp_positions": [original, new_position], "expected_content_revision": detail["content_revision"],
        }, self.session)
        added = backend.official_document_stamp_request(self.conn, detail["id"])["stamp_positions"]
        self.assertEqual(len(added), 2)
        self.assertEqual(added[0]["id"], original["id"])
        self.assertEqual(added[0]["locked_seal_file_id"], original["locked_seal_file_id"])
        kept = {**added[1], "order_index": 1}
        backend.update_official_document_correction(self.conn, detail["id"], {
            "seal_id": self.small, "stamp_positions": [kept], "expected_content_revision": edited["content_revision"],
        }, self.session)
        final = backend.official_document_stamp_request(self.conn, detail["id"])["stamp_positions"]
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["id"], added[1]["id"])
        self.assertEqual(final[0]["locked_seal_file_id"], added[1]["locked_seal_file_id"])

    def test_full_approval_uses_both_locked_assets_even_after_small_current_version_changes(self):
        detail = self.create()
        locked = backend.official_document_stamp_request(self.conn, detail["id"])
        positions = locked["stamp_positions"]
        self.assertEqual(len(positions), 2)
        self.assertNotEqual(positions[0]["locked_seal_sha256"], positions[1]["locked_seal_sha256"])
        old_small = positions[1]["locked_seal_file_id"]
        self.upload_small((0, 190, 0, 255))
        self.assertNotEqual(backend.company_seal_row(self.conn, self.small)["current_file"]["id"], old_small)
        approved = self.fixture.approve_until_after_stamp(detail)
        self.assertEqual(approved["current_status"], "pending_general_affairs_dispatch")
        final = next(f for f in approved["files"] if f["file_type"] == "stamped_pdf")
        _, output = backend.read_file_object_bytes(self.conn, self.conn.execute("SELECT file_object_id FROM official_document_files WHERE id=?", (final["id"],)).fetchone()[0])
        pdf = PdfReader(io.BytesIO(output))
        colors = []
        for page in pdf.pages:
            for image in page.images:
                colors.extend(Image.open(io.BytesIO(image.data)).convert("RGB").getdata())
        self.assertTrue(any(r > 150 and g < 60 and b < 60 for r, g, b in colors), "large red seal missing")
        self.assertTrue(any(b > 150 and r < 60 and g < 60 for r, g, b in colors), "locked blue small seal missing")
        self.assertFalse(any(g > 150 and r < 60 and b < 60 for r, g, b in colors), "used changed current green version")
        self.assertIn("合成印章", "".join(page.extract_text() for page in pdf.pages))

    def test_tampered_secondary_locked_bytes_are_rejected_before_any_render(self):
        detail = self.create()
        request = backend.official_document_stamp_request(self.conn, detail["id"])
        position = request["stamp_positions"][1]
        file_id = self.conn.execute("SELECT file_object_id FROM company_seal_files WHERE id=?", (position["locked_seal_file_id"],)).fetchone()[0]
        original_read = backend.read_file_object_bytes
        def tampered(conn, identity):
            row, data = original_read(conn, identity)
            return (row, b"tampered secondary seal") if identity == file_id else (row, data)
        with mock.patch.object(backend, "read_file_object_bytes", side_effect=tampered):
            with self.assertRaisesRegex(ValueError, "official_locked_seal_hash_mismatch"):
                backend.locked_legacy_official_seal_assets(self.conn, detail, request)

    def test_secondary_inactive_and_cross_company_seals_fail_closed(self):
        detail = self.create()
        request = backend.official_document_stamp_request(self.conn, detail["id"])
        self.conn.execute("UPDATE company_seals SET is_active=0 WHERE id=?", (self.small,))
        with self.assertRaisesRegex(ValueError, "inactive_seal"):
            backend.locked_legacy_official_seal_assets(self.conn, detail, request)
        self.conn.execute("UPDATE company_seals SET is_active=1, company_id='CO-002' WHERE id=?", (self.small,))
        with self.assertRaisesRegex(ValueError, "company_mismatch"):
            backend.locked_legacy_official_seal_assets(self.conn, detail, request)

    def test_supabase_parity_executes_actual_locked_verifiers_for_each_position(self):
        detail = self.create()
        request = backend.official_document_stamp_request(self.conn, detail["id"])
        def rows(table, filters, **kwargs):
            where = " AND ".join(f"{key}=?" for key in filters)
            return [dict(row) for row in self.conn.execute(f"SELECT * FROM {table} WHERE {where}", tuple(filters.values()))]
        def get(table, identity):
            found = rows(table, {"id": identity})
            return found[0] if found else None
        def download(key, bucket):
            identity = self.conn.execute("SELECT id FROM file_objects WHERE storage_key=?", (key,)).fetchone()[0]
            return backend.read_file_object_bytes(self.conn, identity)[1]
        with mock.patch.object(backend, "supabase_filter_rows", side_effect=rows), mock.patch.object(backend, "supabase_get", side_effect=get), mock.patch.object(backend, "supabase_storage_download", side_effect=download):
            assets = backend.supabase_locked_legacy_official_seal_assets(detail, request)
            self.assertEqual([asset[0]["seal_id"] for asset in assets], [self.large, self.small])
            original_download = download
            secondary_key = get("file_objects", assets[1][0]["file_object_id"])["storage_key"]
            with mock.patch.object(backend, "supabase_storage_download", side_effect=lambda key, bucket: b"tampered" if key == secondary_key else original_download(key, bucket)):
                with self.assertRaisesRegex(ValueError, "official_locked_seal_hash_mismatch"):
                    backend.supabase_locked_legacy_official_seal_assets(detail, request)


if __name__ == "__main__":
    unittest.main()
