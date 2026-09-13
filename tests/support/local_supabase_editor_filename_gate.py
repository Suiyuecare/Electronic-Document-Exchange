#!/usr/bin/env python3
"""Real signed Storage + unchanged frontend TUS protocol filename regression.

Only loopback Supabase is accepted. Application row lookups/inserts are isolated
in-memory fixtures; signed tokens, TUS POST/PATCH/HEAD, source-byte downloads and
immutable-path uploads are real local Storage calls. This is not a hosted SSO
or physical-device claim. No documents are submitted, sealed or dispatched.
"""
from __future__ import annotations

import base64
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from unittest import mock
from urllib.parse import urlparse
import uuid

from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FilenameGateFailure(RuntimeError):
    pass


def require(value, code):
    if not value:
        raise FilenameGateFailure(code)


def run_frontend(api_url, intent, data, file_name, mime_type, *, interrupt=False):
    completed = subprocess.run(
        ['node', str(ROOT / 'tests/support/editor_tus_frontend_runner.cjs')],
        input=json.dumps({
            'localOrigin': api_url,
            'intent': intent,
            'fileName': file_name,
            'mimeType': mime_type,
            'dataBase64': base64.b64encode(data).decode('ascii'),
            'interruptAfterFirstPatch': interrupt,
        }), text=True, capture_output=True, timeout=90, check=False,
    )
    require(completed.returncode == 0, 'filename_gate_frontend_runner_failed')
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError):
        raise FilenameGateFailure('filename_gate_frontend_response_invalid') from None
    require(result.get('actualProductionClient'), 'filename_gate_production_client_required')
    return result


def pdf_bytes(*, large=False):
    stream = io.BytesIO()
    doc = canvas.Canvas(stream, pagesize=A4, pageCompression=0, invariant=1)
    doc.setTitle('Synthetic isolated editor filename regression')
    doc.drawString(72, A4[1] - 72, 'Deidentified PDF upload acceptance')
    if large:
        # Valid PDF content-stream comments produce >6 MiB without adding
        # visible page content. This exercises a committed chunk + HEAD resume.
        doc._code.append('%' + 'x' * (6 * 1024 * 1024 + 4096) + '\n')
    doc.showPage()
    doc.save()
    return stream.getvalue()


def image_bytes(format_name):
    stream = io.BytesIO()
    Image.new('RGB', (8, 8), (255, 255, 255)).save(stream, format=format_name)
    return stream.getvalue()


def make_intent(backend, document_id, data, file_name, mime_type, asset_kind):
    inserted = {}

    def insert(table, payload):
        require(table in {'official_document_editor_assets', 'official_document_editor_storage_jobs'},
                'filename_gate_unexpected_table')
        inserted[table] = dict(payload)
        return dict(payload)

    with ExitStack() as stack:
        for name, value in {
            'require_production_editor_runtime_ready': None,
            'supabase_official_document_row': {'id': document_id, 'company_id': 'CI-FILENAME-CO'},
            '_supabase_editor_assert_document_access': {'id': 'CI-FILENAME-USER'},
            'supabase_cleanup_stale_official_editor_uploads': None,
            '_supabase_editor_latest_revision': {'id': 'CI-FILENAME-REV', 'revision_no': 1},
        }.items():
            stack.enter_context(mock.patch.object(backend, name, return_value=value))
        stack.enter_context(mock.patch.object(backend, 'supabase_insert', side_effect=insert))
        intent = backend.supabase_create_official_editor_upload_intent(document_id, {
            'asset_kind': asset_kind, 'file_name': file_name, 'mime_type': mime_type,
            'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
        }, {'user': {'id': 'CI-FILENAME-USER'}})
    asset = inserted['official_document_editor_assets']
    job = inserted['official_document_editor_storage_jobs']
    require(asset['file_name'] == file_name, 'filename_gate_original_name_changed')
    require(intent['asset']['fileName'] == file_name, 'filename_gate_public_name_changed')
    require(json.loads(asset['metadata_json']).get('storage_key_version') == 2,
            'filename_gate_key_version_missing')
    require(bool(re.fullmatch(r'[A-Za-z0-9_./-]+', intent['path'])), 'filename_gate_staging_key_unsafe')
    require(bool(re.fullmatch(r'[A-Za-z0-9_./-]+', job['final_path'])), 'filename_gate_final_key_unsafe')
    return intent, job


def main():
    api_url = os.environ.get('EDOC_LOCAL_SUPABASE_URL', '').rstrip('/')
    parsed = urlparse(api_url)
    require(parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost'}
            and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment,
            'filename_gate_loopback_required')
    service_key = os.environ.get('EDOC_LOCAL_SUPABASE_SERVICE_ROLE_KEY', '')
    anon_key = os.environ.get('EDOC_LOCAL_SUPABASE_ANON_KEY', '')
    require(service_key and anon_key, 'filename_gate_local_keys_missing')
    os.environ.update({
        'EDOC_DB_MODE': 'supabase', 'SUPABASE_URL': api_url,
        'SUPABASE_SERVICE_ROLE_KEY': service_key, 'SUPABASE_ANON_KEY': anon_key,
        'EDOC_STORAGE_PROVIDER': 'supabase', 'EDOC_STORAGE_BUCKET': 'edoc-private',
        'EDOC_OBJECT_STORAGE_URL': f'{api_url}/storage/v1',
        'EDOC_STORAGE_PUBLISHABLE_KEY': anon_key,
    })
    import backend
    require(backend.object_storage_endpoint() == f'{api_url}/storage/v1',
            'filename_gate_storage_origin_mismatch')
    # Only the cloud-hostname policy is adapted after the hard loopback gate.
    # The production signer and no-redirect Storage HTTP paths remain intact.
    backend._supabase_storage_endpoint_issue = lambda: ''
    suffix = uuid.uuid4().hex[:12].upper()
    document_id = f'CI-FILENAME-{suffix}'
    small_pdf = pdf_bytes()
    cases = [
        ('traditional_chinese', '驗收 合約.pdf', 'application/pdf', 'source_pdf', small_pdf),
        ('percent_brackets', 'agreement [50%].pdf', 'application/pdf', 'source_pdf', small_pdf),
        ('emoji', 'contract-📄.pdf', 'application/pdf', 'source_pdf', small_pdf),
        ('accented_merge', 'résumé.pdf', 'application/pdf', 'import_pdf', small_pdf),
        ('ascii_spaces', 'agreement with spaces.pdf', 'application/pdf', 'source_pdf', small_pdf),
        ('png_image', '圖片 [50%].png', 'image/png', 'image', image_bytes('PNG')),
        ('jpeg_image', '圖片 📄.jpeg', 'image/jpeg', 'image', image_bytes('JPEG')),
        ('multi_chunk_resume', '多頁 合約.pdf', 'application/pdf', 'source_pdf', pdf_bytes(large=True)),
    ]
    cleanup = set()
    results = []
    try:
        for label, file_name, mime_type, asset_kind, data in cases:
            intent, job = make_intent(backend, document_id, data, file_name, mime_type, asset_kind)
            cleanup.add(intent['path'])
            cleanup.add(job['final_path'])
            if label in {'traditional_chinese', 'percent_brackets', 'emoji', 'accented_merge'}:
                legacy_path = f"editor/{document_id}/{intent['asset_id']}-{file_name}"
                token = backend._supabase_create_signed_upload_token(legacy_path, 'edoc-private')
                legacy = run_frontend(api_url, {
                    **intent, 'path': legacy_path, 'upload_token': token,
                    'metadata': {**intent['metadata'], 'objectName': legacy_path},
                }, data, file_name, mime_type)
                require(not legacy['ok'] and legacy['status'] == 400
                        and legacy['invalidKeyRejected']
                        and legacy['code'] == 'editor_tus_invalid_object_key',
                        'filename_gate_legacy_failure_not_reproduced')
                require(legacy['trace'] == [{'method': 'POST', 'status': 400}],
                        'filename_gate_legacy_unexpected_upload')
            result = run_frontend(api_url, intent, data, file_name, mime_type,
                                  interrupt=label == 'multi_chunk_resume')
            require(result['ok'] and result['offset'] == len(data) and result['progressComplete']
                    and result['fileNamePreserved'], 'filename_gate_safe_upload_failed')
            require(result['trace'][0] == {'method': 'POST', 'status': 201},
                    'filename_gate_safe_create_failed')
            if label == 'multi_chunk_resume':
                require(result['interrupted'] and any(row['method'] == 'HEAD' and row['status'] in {200, 204}
                        for row in result['trace']), 'filename_gate_resume_not_exercised')
                require(sum(row['method'] == 'PATCH' for row in result['trace']) >= 2,
                        'filename_gate_chunking_not_exercised')
            downloaded = backend.supabase_storage_download(intent['path'], 'edoc-private')
            require(hashlib.sha256(downloaded).digest() == hashlib.sha256(data).digest(),
                    'filename_gate_source_hash_changed')
            backend.supabase_storage_upload(job['final_path'], downloaded, mime_type, 'edoc-private')
            final_bytes = backend.supabase_storage_download(job['final_path'], 'edoc-private')
            require(hashlib.sha256(final_bytes).digest() == hashlib.sha256(data).digest(),
                    'filename_gate_final_hash_changed')
            # A valid token must not permit another object path. No upload is
            # allowed and no policy or upsert bypass is introduced.
            tampered = run_frontend(api_url, {**intent, 'path': intent['path'] + '.other'},
                                    data, file_name, mime_type)
            require(not tampered['ok'] and tampered['status'] in {400, 401, 403},
                    'filename_gate_signature_scope_not_enforced')
            require(len(tampered['trace']) == 1 and tampered['trace'][0]['method'] == 'POST',
                    'filename_gate_tampered_path_received_bytes')
            results.append({'case': label, 'passed': True,
                            'legacy_rejected': label in {'traditional_chinese', 'percent_brackets', 'emoji', 'accented_merge'},
                            'resumed': result['interrupted'], 'source_and_final_hash_match': True,
                            'original_name_retained': True, 'signature_scope_enforced': True})
    finally:
        for storage_path in cleanup:
            backend.supabase_storage_delete(storage_path, 'edoc-private')
    report = {'passed': True, 'cases': results, 'production_client_executed': True,
              'real_loopback_storage': True, 'application_rows': 'in_memory_fixtures',
              'hosted_storage_tested': False, 'physical_browser_tested': False}
    target = ROOT / 'tests/.artifacts/editor-filename-protocol/report.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except FilenameGateFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # Provider exceptions may carry a signed capability URL or object name.
        # Do not let an unexpected integration error expose either in CI logs.
        print('filename_gate_unexpected_integration_failure', file=sys.stderr)
        raise SystemExit(1) from None
    except Exception:
        # Never emit upstream errors: they can contain signed URLs or keys.
        print('filename_gate_unexpected_failure', file=sys.stderr)
        raise SystemExit(1) from None
