"""Generate de-identified compose PDF visual fixtures; never calls a provider."""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend
from pypdf import PdfReader


def run(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    report = {"scope": "local_synthetic_pdf_only", "renderer": backend.OFFICIAL_PDF_RENDERER_VERSION, "fixtures": []}
    for name, email in (
        ("compose-electronic-standard", "document.operator@example.test"),
        ("compose-electronic-long-contact", "long.document.operator.department@example.test"),
    ):
        payload = {
            "doc_no": "測試字第1150908001號", "dispatch_date": "2026-12-11",
            "company_name": "去識別化測試股份有限公司", "doc_type": "函",
            "recipient": "測試主管機關", "subject": "檢送去識別化測試資料一份，請查照。",
            "description": "一、本公文僅供隔離測試，不含真實個資。\n二、測試發文日期、附件文字與聯絡資料版面。",
            "attachment_details": "測試附件一份（可編輯的附件說明）", "output_mode": "electronic",
            "contact_address": "110測試市測試區測試路一段364巷6號1樓",
            "contact_owner": "測試承辦人", "contact_phone": "02-66045432 #999",
            "contact_fax": "N/A", "contact_email": email,
        }
        data = backend.build_official_pdf(payload)
        pdf = output / f"{name}.pdf"
        pdf.write_bytes(data)
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert "115年12月11日" in text
        assert "附件：測試附件一份（可編輯的附件說明）" in text
        assert "傳真：N/A" in text
        assert all(abs(float(page.mediabox.width) - backend.A4_WIDTH_PT) < 0.1 for page in reader.pages)
        subprocess.run(["pdftoppm", "-r", "120", "-png", str(pdf), str(output / name)], check=True, capture_output=True)
        report["fixtures"].append({"name": name, "pages": len(reader.pages), "dateMatched": True, "attachmentMatched": True, "a4": True})
    (output / "pdf-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output), ensure_ascii=False))
