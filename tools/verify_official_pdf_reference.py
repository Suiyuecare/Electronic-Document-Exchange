"""Create three synthetic reference-manual PDF fixtures and PNG QA renders.

No network, real records, signatures, or seals are used. The supplied manual
is read only for its SHA-256; report and fixtures must be new output files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import backend  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", default=ROOT / "output" / "pdf", type=Path)
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    digest_before = hashlib.sha256(source.read_bytes()).hexdigest()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = {
        "company_name": "測試法人研究協會",
        "doc_type": "函",
        "doc_no": "測試字第1150901001號",
        "dispatch_date": "2026-09-01",
        "agency_name": "測試收文機關",
        "subject": "檢送去識別化排版測試計畫1份，請查照。",
        "body": "說明：\n一、本函僅供版面驗收，不具正式發文效力。\n二、檢附資料均為去識別化測試內容。",
        "contact_address": "測試市測試區測試路1號",
        "contact_owner": "測試承辦人",
        "contact_phone": "(00)0000-0000",
        "contact_fax": "N/A",
        "contact_email": "test@example.invalid",
        "attachments_summary": "去識別化測試計畫1份",
    }
    nested = (
        "一、本項為去識別化排版驗收，確認本文分項與換行位置；所列內容不代表正式機關之決定。\n"
        "(一)核對章節及標號層級，並檢查換行後之文字是否對齊原項次本文，不得遺漏或改寫資料。\n"
        "１、採用教材字級與黑白楷體，長段落應保持完整，不以縮小文字代替正常分頁。\n"
        "(１)以去識別化內容測試多頁輸出，確認末頁正本與副本資料完整，並保留上下邊界。"
    )
    cases = {
        "official-manual-short": base,
        "official-manual-long-heading": {**base, "company_name": "測試法人全國公共服務與教育訓練品質研究發展推廣協會", "body": "說明：\n" + nested},
        "official-manual-multipage": {**base, "body": "說明：\n" + "\n".join([nested] * 3) + "\n辦法：\n一、完成格式驗收後，始得提供承辦人確認。\n擬辦：\n一、擬依核定內容辦理，陳核。"},
    }
    report = {"source": {"path": str(source), "sha256": digest_before, "size_bytes": source.stat().st_size}, "renderer": backend.OFFICIAL_PDF_RENDERER_VERSION, "contains_personal_data": False, "files": []}
    for stem, document in cases.items():
        pdf_path = output / f"{stem}.pdf"
        if pdf_path.exists() or pdf_path.is_symlink() or pdf_path.resolve() == source:
            raise ValueError(f"refusing_to_overwrite_output: {pdf_path}")
        package = backend.build_official_pdf_package(document)
        pdf_path.write_bytes(package["data"])
        with fitz.open(stream=package["data"], filetype="pdf") as pdf:
            png_paths = []
            for index, page in enumerate(pdf):
                png_path = output / f"{stem}-page-{index + 1}.png"
                if png_path.exists() or png_path.is_symlink() or png_path.resolve() == source:
                    raise ValueError(f"refusing_to_overwrite_output: {png_path}")
                page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6)).save(png_path)
                png_paths.append(str(png_path))
        report["files"].append({"pdf": str(pdf_path), "sha256": hashlib.sha256(package["data"]).hexdigest(), "layout": package["layout"], "pngs": png_paths})
    digest_after = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest_after != digest_before:
        raise ValueError("source_hash_changed")
    report["source"]["unchanged"] = True
    report_path = output / "official-manual-layout-qa.json"
    if report_path.exists() or report_path.is_symlink() or report_path.resolve() == source:
        raise ValueError("refusing_to_overwrite_qa_report")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
