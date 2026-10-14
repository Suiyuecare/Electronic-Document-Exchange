"""Synthetic maintenance authorization/pipeline tests; never production SSO."""
import base64
import hashlib
import io
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from PIL import Image
import backend
import seal_operator_import_120 as operator
import seal_scan_20261013 as scan


class OperatorImportTest(unittest.TestCase):
    def setUp(self):
        self.secret="synthetic-test-token-not-a-real-secret-123456"
        self.now=int(time.time())
        self.env={"EDOC_NATIVE120_SEAL_IMPORT_KEY_SHA256":hashlib.sha256(self.secret.encode()).hexdigest(),
                  "EDOC_NATIVE120_SEAL_IMPORT_STARTED_AT":str(self.now-1),
                  "EDOC_NATIVE120_SEAL_IMPORT_EXPIRES_AT":str(self.now+600)}

    def test_key_missing_wrong_expired_overlong_or_reversed_is_denied(self):
        self.assertTrue(operator.authorize(self.secret,self.env))
        for token,env in (("",self.env),("wrong"*12,self.env),(self.secret,{}),
                          (self.secret,{**self.env,"EDOC_NATIVE120_SEAL_IMPORT_EXPIRES_AT":str(self.now)}),
                          (self.secret,{**self.env,"EDOC_NATIVE120_SEAL_IMPORT_EXPIRES_AT":str(self.now+3601)}),
                          (self.secret,{**self.env,"EDOC_NATIVE120_SEAL_IMPORT_STARTED_AT":str(self.now+1)})):
            with self.assertRaises(PermissionError): operator.authorize(token,env)

    def fixture(self):
        buffer=io.BytesIO(); Image.new("RGBA",(125,124),(160,0,0,255)).save(buffer,format="PNG")
        self.data=buffer.getvalue(); digest=hashlib.sha256(self.data).hexdigest()
        r=(digest,*scan._ROWS[0][1:])
        self.entry=r
        seal={"id":r[2],"company_id":r[1],"seal_category":r[3],"seal_size_type":r[4],"is_active":True}
        batch={"status":"open","key_sha256":self.env["EDOC_NATIVE120_SEAL_IMPORT_KEY_SHA256"],"source_pdf_sha256":scan.SOURCE_SHA256,
               "started_at_epoch":self.now-1,"expires_at_epoch":self.now+600}
        row={"id":"SFILE-APPROVED-"+digest,"seal_id":r[2],"file_hash":digest.upper(),"pixel_width":r[5],"pixel_height":r[6],
             "source_aspect_ratio":r[5]/r[6],"render_width_mm":r[7],"render_height_mm":r[8],
             "dimension_policy_version":scan.POLICY,"dimension_validated":True,"is_current":True}
        runtime=SimpleNamespace(USE_SUPABASE=True,is_production=mock.Mock(return_value=True),require_production_editor_runtime_ready=mock.Mock(),
            supabase_filter_rows=mock.Mock(side_effect=lambda table,*a,**k:[batch] if table=="approved_native120_scan_import_batches" else []),
            supabase_get=mock.Mock(side_effect=lambda table,*a:seal if table=="company_seals" else {"id":r[1]}),
            assert_seal_company_scope=mock.Mock(),decode_seal_file_content=backend.decode_seal_file_content,
            validate_seal_file_upload=backend.validate_seal_file_upload,seal_policy=backend.seal_policy,seal_file_av_is_clean=backend.seal_file_av_is_clean,
            scan_seal_upload_bytes=mock.Mock(return_value=("已通過","synthetic-fixture-clean")),
            supabase_storage_upload=mock.Mock(),supabase_storage_download=mock.Mock(return_value=self.data),
            supabase_request=mock.Mock(return_value={"file":row,"import_status":"registered","completed_file_count":1,"batch_status":"open"}),
            supabase_company_seal_row=mock.Mock(return_value={"selectable":True,"availability_reason":"ready","current_file":row}),
            EDOC_SEAL_STORAGE_BUCKET="synthetic-private-vault",EDOC_SCAN_ENGINE="synthetic-fixture-engine")
        payload={"source_pdf_sha256":scan.SOURCE_SHA256,"seal_id":r[2],"content_base64":base64.b64encode(self.data).decode()}
        return runtime,payload,r

    def test_pipeline_uses_actual_bytes_validation_scan_readback_and_atomic_rpc(self):
        runtime,payload,r=self.fixture()
        with mock.patch.object(scan,"_ROWS",(r,)):
            result=operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        self.assertTrue(result["ok"])
        self.assertTrue(result["catalog_selectable"])
        runtime.scan_seal_upload_bytes.assert_called_once()
        runtime.supabase_storage_upload.assert_called_once()
        runtime.supabase_storage_download.assert_called_once()
        params=runtime.supabase_request.call_args.args[2]
        self.assertEqual(params["p_sha256"],r[0].upper())
        self.assertNotIn("p_actor",params)
        self.assertEqual(params["p_width_mm"],r[7])
        self.assertEqual(params["p_height_mm"],r[8])

    def test_wrong_source_slot_hash_or_caller_identity_never_writes(self):
        runtime,payload,r=self.fixture()
        for changed in ({**payload,"source_pdf_sha256":"0"*64},{**payload,"seal_id":"wrong-slot"},
                        {**payload,"actor":"fake-ceo"},{**payload,"content_base64":base64.b64encode(b"wrong").decode()}):
            with mock.patch.object(scan,"_ROWS",(r,)), self.assertRaises(ValueError):
                operator.import_one(runtime,operator.authorize(self.secret,self.env),changed)
        runtime.supabase_storage_upload.assert_not_called()
        runtime.supabase_request.assert_not_called()

    def test_no_av_provider_never_uploads_or_marks_current(self):
        runtime,payload,r=self.fixture()
        runtime.scan_seal_upload_bytes.side_effect=RuntimeError("real_provider_unavailable")
        with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaisesRegex(RuntimeError,"provider_unavailable"):
            operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        runtime.supabase_storage_upload.assert_not_called()
        runtime.supabase_request.assert_not_called()

    def test_nonproduction_cannot_use_fixture_scanner_with_a_real_database(self):
        runtime,payload,r=self.fixture(); runtime.is_production.return_value=False
        with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaisesRegex(RuntimeError,"production_runtime_required"):
            operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        runtime.supabase_filter_rows.assert_not_called()
        runtime.scan_seal_upload_bytes.assert_not_called()
        runtime.supabase_storage_upload.assert_not_called()

    def test_existing_different_current_and_bad_storage_are_not_overwritten(self):
        runtime,payload,r=self.fixture()
        batch=runtime.supabase_filter_rows("approved_native120_scan_import_batches",{})[0]
        runtime.supabase_filter_rows.side_effect=lambda table,*a,**k:[batch] if table=="approved_native120_scan_import_batches" else [{"file_hash":"wrong"}]
        with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaisesRegex(ValueError,"current_conflict"):
            operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        runtime.supabase_storage_upload.assert_not_called()
        runtime.supabase_request.assert_not_called()
        runtime,payload,r=self.fixture(); runtime.supabase_storage_download.return_value=b"wrong"
        with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaisesRegex(ValueError,"storage_verification_failed"):
            operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        runtime.supabase_request.assert_not_called()

    def test_http_requires_temporary_key_before_reading_body(self):
        handler=backend.Handler.__new__(backend.Handler)
        handler.headers={"Content-Length":"10"}
        handler.send_json=mock.Mock(); handler.read_json=mock.Mock()
        with mock.patch.dict(os.environ,self.env):
            handler.handle_api("POST","/api/admin/approved-native120-seal-import",{})
        handler.send_json.assert_called_once_with({"error":"unauthorized"},401)
        handler.read_json.assert_not_called()

    def test_committed_file_does_not_claim_catalog_ready_if_projection_is_missing_or_foreign(self):
        for catalog in ({"selectable":False,"availability_reason":"missing_current"},
                        {"selectable":True,"availability_reason":"ready","current_file":{"id":"foreign","file_hash":"0"*64}}):
            runtime,payload,r=self.fixture()
            runtime.supabase_company_seal_row.return_value=catalog
            with mock.patch.object(scan,"_ROWS",(r,)):
                result=operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
            self.assertTrue(result["ok"])
            self.assertFalse(result["catalog_selectable"])

    def test_old_source_capability_names_cannot_authorize_native120(self):
        old_env={key.replace("EDOC_NATIVE120_SEAL_IMPORT","EDOC_APPROVED_SEAL_IMPORT"):value for key,value in self.env.items()}
        with self.assertRaises(PermissionError):
            operator.authorize(self.secret,old_env)

    def test_expiry_after_scan_stops_before_storage_or_commit(self):
        runtime,payload,r=self.fixture()
        context=operator.authorize(self.secret,self.env)
        with mock.patch.object(scan,"_ROWS",(r,)),mock.patch.object(operator.time,"time",side_effect=[self.now,self.now+601]),self.assertRaises(PermissionError):
            operator.import_one(runtime,context,payload)
        runtime.supabase_storage_upload.assert_not_called()
        runtime.supabase_request.assert_not_called()

    def test_known_rpc_rejection_is_never_reconciled_as_success(self):
        for error in (ValueError("approved_scan_import_permit_closed"),RuntimeError("supabase_request_failed:403:42501")):
            runtime,payload,r=self.fixture(); runtime.supabase_request.side_effect=error
            with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaises(type(error)):
                operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
            self.assertFalse(any(call.args[0] in {"audit_logs","company_seal_files"} for call in runtime.supabase_get.call_args_list))

    def test_unknown_transport_without_matching_batch_audit_is_not_success(self):
        runtime,payload,r=self.fixture(); runtime.supabase_request.side_effect=TimeoutError()
        with mock.patch.object(scan,"_ROWS",(r,)),self.assertRaisesRegex(RuntimeError,"commit_unconfirmed"):
            operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)

    def test_lost_existing_custodian_response_uses_only_verified_batch_audit_anchor(self):
        runtime,payload,r=self.fixture(); runtime.supabase_request.side_effect=TimeoutError()
        seal=runtime.supabase_get("company_seals",r[2])
        old_file={"id":"synthetic-custodian-version","seal_id":r[2],"file_hash":r[0].upper(),"pixel_width":r[5],"pixel_height":r[6],
                  "source_aspect_ratio":r[5]/r[6],"render_width_mm":r[7],"render_height_mm":r[8],
                  "dimension_policy_version":scan.POLICY,"dimension_validated":True,"is_current":True,"file_object_id":"synthetic-backing",
                  "file_size":len(self.data),"file_mime_type":"image/png","file_storage_key":"synthetic-original-key"}
        backing={"id":"synthetic-backing","sha256":r[0].upper(),"size_bytes":len(self.data),"mime_type":"image/png","storage_key":"synthetic-original-key","scan_status":"clean"}
        audit={"actor":operator.ACTOR,"action":"operator_import_native120_scan","target_type":"company_seal_files","target_id":old_file["id"],"detail":"source_pdf_sha256="+scan.SOURCE_SHA256}
        batch={"status":"open","key_sha256":self.env["EDOC_NATIVE120_SEAL_IMPORT_KEY_SHA256"],"source_pdf_sha256":scan.SOURCE_SHA256,
               "started_at_epoch":self.now-1,"expires_at_epoch":self.now+600,"completed_file_count":1}
        runtime.supabase_filter_rows.side_effect=lambda table,*a,**k:[batch] if table=="approved_native120_scan_import_batches" else [old_file]
        runtime.supabase_get.side_effect=lambda table,*a: {"company_seals":seal,"companies":{"id":r[1]},"file_objects":backing,"audit_logs":audit,"company_seal_files":old_file}[table]
        runtime.supabase_company_seal_row.return_value={"selectable":True,"availability_reason":"ready","current_file":old_file}
        with mock.patch.object(scan,"_ROWS",(r,)):
            result=operator.import_one(runtime,operator.authorize(self.secret,self.env),payload)
        self.assertEqual(result["file_id"],old_file["id"])
        self.assertEqual(result["import_status"],"already_registered")
        runtime.supabase_storage_upload.assert_not_called()


if __name__ == "__main__": unittest.main()
