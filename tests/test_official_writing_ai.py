"""Offline composition regression tests. All identities/references are fixtures."""

import io
import json
import unittest
import urllib.error
from unittest import mock

import backend
import official_writing as writing


class OfficialWritingRulesTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "plainText": "我們長照的課程要來去申請新的積分帳號，因為在115年12月11號有獲得到評鑑通過的公文，公文字號是 測試字第11500000001號",
            "documentDate": "2026-09-12",
            "issuerName": "測試股份有限公司",
            "recipient": "測試主管機關",
            "attachments": [],
            "attachmentDetails": "",
        }

    def test_dates_convert_equivalently_and_never_repair_invalid_dates(self):
        for value, expected in (
            ("115年12月11號", "民國115年12月11日"),
            ("2026-09-12", "民國115年9月12日"),
            ("中華民國115年09月12日", "民國115年9月12日"),
            ("民國115/09/12", "民國115年9月12日"),
            ("115年2月30日", "115年2月30日"),
            ("2024/2/29", "民國113年2月29日"),
            ("測試字第11500000001號", "測試字第11500000001號"),
        ):
            with self.subTest(value=value):
                self.assertEqual(writing.normalize_dates(value), expected)

    def test_screenshot_regression_formal_dynamic_explanation_and_warning(self):
        draft = writing.fallback_draft(self.payload)
        self.assertEqual(draft["subject"], "有關本公司為長照課程申請新積分帳號一案，請惠予審核。")
        self.assertEqual(len(draft["body"].splitlines()), 2)
        self.assertNotRegex(draft["subject"] + draft["body"], r"我們|要來去|有獲得到|依業務需要|檢附")
        self.assertIn("民國115年12月11日", draft["body"])
        self.assertIn("測試字第11500000001號", draft["body"])
        self.assertIn("其日期及內容尚待核對", draft["body"])
        self.assertIn("晚於本件發文日期", " ".join(draft["warnings"]))
        self.assertFalse(draft["usedOpenAI"])
        self.assertIn("非 AI 生成", draft["notice"])

    def test_short_input_does_not_generate_three_padding_points(self):
        result = writing.fallback_draft({"plainText": "請協助辦理年度資料更新"})
        self.assertEqual(result["body"], "一、辦理年度資料更新。")
        self.assertNotIn("二、", result["body"])
        self.assertNotIn("依業務需要", result["body"])

    def test_long_explanation_numbering_does_not_crash(self):
        result = writing.fallback_draft({"plainText": "；".join(f"確認第{n}項作業" for n in range(1, 151))})
        self.assertEqual(len(result["body"].splitlines()), 150)
        self.assertTrue(result["body"].splitlines()[100].startswith("一百零一、"))
        self.assertTrue(result["body"].splitlines()[-1].startswith("一百五十、"))

    def test_thousands_separator_does_not_split_amount_into_two_points(self):
        result = writing.fallback_draft({"plainText": "申請補助10,000元，預計辦理課程"})
        self.assertIn("10,000元", result["body"])
        self.assertEqual(len(result["body"].splitlines()), 2)

    def test_unverified_attachment_statement_does_not_erase_source_date_or_number(self):
        result = writing.fallback_draft({"plainText": "申請課程，檢附115年9月1日測試字第11500000001號函影本1份", "attachments": []})
        self.assertIn("民國115年9月1日", result["body"])
        self.assertIn("測試字第11500000001號", result["body"])
        self.assertIn("1份", result["body"])
        self.assertNotIn("檢附", result["body"])
        self.assertIn("是否相符尚待核對", result["body"])
        self.assertTrue(result["warnings"])

    def test_future_plan_not_misdiagnosed_as_future_historical_reference(self):
        result = writing.fallback_draft({"plainText": "預計於115年12月11日辦理教育訓練", "documentDate": "2026-09-12"})
        self.assertFalse(result["warnings"])
        self.assertIn("預計於民國115年12月11日", result["body"])

    def test_invalid_date_is_preserved_and_warned(self):
        result = writing.fallback_draft({"plainText": "預計115年2月30日辦理課程", "documentDate": "2026-09-12"})
        self.assertIn("115年2月30日", result["body"])
        self.assertIn("無效", result["warnings"][0])

    def test_missing_attachment_does_not_become_attachment_claim(self):
        for extra in ({"attachmentDetails": "課程計畫各1份"}, {"plainText": "申請辦理課程，檢附課程計畫1份"}):
            result = writing.fallback_draft({**self.payload, **extra})
            self.assertNotRegex(result["body"], r"檢附|檢送")
            self.assertIn("尚無已上傳附件", " ".join(result["warnings"]))

    def test_real_attachment_names_are_used_without_guessing_counts(self):
        result = writing.fallback_draft({"plainText": "申請辦理教育訓練課程", "attachments": ["課程計畫_v2.pdf", "師資名冊.docx"], "attachmentDetails": "使用者可編輯之說明"})
        self.assertIn("檢附「課程計畫_v2.pdf」、「師資名冊.docx」", result["body"])
        self.assertNotIn("各1份", result["body"])

    def test_does_not_change_registered_name_tai_character(self):
        result = writing.fallback_draft({"plainText": "台安公司已完成資料更新"})
        self.assertIn("台安公司已完成", result["body"])
        self.assertNotIn("臺安", result["body"])

    def test_existing_completed_status_is_not_rewritten_as_planned(self):
        result = writing.fallback_draft({"plainText": "本公司負責人已由王測甲變更為李測乙，已於115年9月1日完成登記"})
        self.assertIn("已由王測甲變更為李測乙", result["body"])
        self.assertNotIn("擬由", result["body"])

    def test_quality_guard_allows_qualified_future_reference(self):
        errors = writing.quality_errors(
            "有關本公司申請長照課程積分帳號一案，請惠予審核。",
            "一、本公司擬申請長照課程新積分帳號。\n二、所提供資料載有民國115年12月11日測試字第11500000001號評鑑結果函，其日期及內容尚待核對。",
            self.payload,
        )
        self.assertEqual(errors, [])

    def test_quality_guard_rejects_unqualified_future_approval(self):
        errors = writing.quality_errors(
            "有關本公司申請長照課程積分帳號一案，請惠予審核。",
            "一、本公司已獲評鑑通過，依民國115年12月11日測試字第11500000001號函辦理。",
            self.payload,
        )
        self.assertIn("future_reference_claimed_as_fact", errors)

    def test_quality_guard_rejects_changed_date_reference_and_quantity(self):
        payload = {"plainText": "申請10萬元補助，依115年9月1日測試字第11500000001號函辦理"}
        errors = writing.quality_errors(
            "有關本公司申請補助一案，請惠予審核。",
            "一、依民國115年9月2日測試字第11500000002號函，申請20萬元補助。",
            payload,
        )
        self.assertIn("source_fact_missing_or_changed", errors)
        self.assertIn("invented_date", errors)
        self.assertIn("invented_reference", errors)
        self.assertIn("number_changed_or_invented", errors)

    def test_quality_guard_rejects_mixed_timeline_application_claim(self):
        payload = {"plainText": "本公司已完成課程評鑑，擬申請新的課程積分帳號"}
        subject = "有關本公司申請課程積分帳號一案，請惠予審核。"
        unsafe = "一、本公司已完成課程評鑑。\n二、課程積分帳號已核准。"
        self.assertIn("planned_scope_became_completed", writing.quality_errors(subject, unsafe, payload))
        safe = "一、本公司已完成課程評鑑。\n二、本公司擬申請新課程積分帳號。"
        self.assertEqual(writing.quality_errors(subject, safe, payload), [])

    def test_quality_guard_rejects_filler_and_colloquial_copy(self):
        errors = writing.quality_errors("有關我們要來去申請帳號一案，請惠予審核。", "一、依業務需要辦理本案。", {"plainText": "我們要來去申請新的帳號"})
        self.assertIn("informal_or_empty_filler", errors)

    def test_quality_guard_rejects_missing_and_invented_attachments(self):
        subject = "有關本公司申請課程一案，請惠予審核。"
        payload = {"plainText": "申請辦理教育訓練課程", "attachments": ["真實計畫.pdf"]}
        for body, code in (
            ("一、檢附課程資料。", "attachment_name_missing_or_changed"),
            ("一、檢附「真實計畫.pdf」及「虛構證書.pdf」。", "invented_attachment_name"),
            ("一、檢附「真實計畫.pdf」各1份。", "invented_attachment_count"),
        ):
            with self.subTest(body=body):
                self.assertIn(code, writing.quality_errors(subject, body, payload))

    def test_quality_guard_allows_stated_attachment_count_string(self):
        payload = {"plainText": "申請辦理教育訓練課程", "attachments": ["真實計畫.pdf"], "attachmentDetails": "真實計畫.pdf 2份"}
        errors = writing.quality_errors("有關本公司申請課程一案，請惠予審核。", "一、本公司申請辦理教育訓練課程。\n二、檢附「真實計畫.pdf」2份。", payload)
        self.assertEqual(errors, [])

    def test_quality_guard_rejects_invented_legal_basis(self):
        errors = writing.quality_errors("有關本公司申請課程一案，請惠予審核。", "一、依據長期照顧服務法第9條辦理本案。", {"plainText": "申請辦理教育訓練課程"})
        self.assertIn("invented_legal_basis", errors)

    def test_quality_guard_preserves_personnel_names_and_direction(self):
        payload = {"plainText": "本公司負責人擬由王測甲變更為李測乙"}
        subject = "有關本公司負責人變更一案，請查照。"
        self.assertEqual(writing.quality_errors(subject, "一、本公司負責人擬由王測甲變更為李測乙。", payload), [])
        self.assertIn("person_change_reversed", writing.quality_errors(subject, "一、本公司負責人擬由李測乙變更為王測甲。", payload))
        self.assertIn("person_identity_missing_or_changed", writing.quality_errors(subject, "一、本公司負責人擬由王測甲變更為陳測丙。", payload))


class OfficialWritingEndpointTests(unittest.TestCase):
    def setUp(self):
        self.audit = mock.patch.object(backend, "record_ai_compose_audit").start()
        self.network = mock.patch.object(backend, "_urlopen_no_redirect").start()
        mock.patch.object(backend, "OPENAI_API_KEY", "fake-offline-test-key").start()
        mock.patch.object(backend, "OPENAI_MODEL", "existing-test-model").start()
        self.addCleanup(mock.patch.stopall)
        self.payload = {"plainText": "我們要來去申請新的課程帳號", "recipient": "測試機關", "documentDate": "2026-09-12", "issuerName": "測試公司", "attachmentDetails": "", "attachments": [], "role": "test-actor"}

    def response(self, draft):
        self.network.return_value.__enter__.return_value.read.return_value = json.dumps({"output_text": json.dumps(draft, ensure_ascii=False)}, ensure_ascii=False).encode()

    def test_existing_api_model_and_request_contract_are_preserved(self):
        self.response({"subject": "有關本公司申請課程帳號一案，請惠予審核。", "body": "一、本公司擬申請新課程帳號。"})
        result = backend.ai_compose_official_draft(None, self.payload)
        self.assertTrue(result["usedOpenAI"])
        self.assertEqual(result["model"], "existing-test-model")
        request = self.network.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
        sent = json.loads(request.data)
        self.assertEqual(sent["model"], "existing-test-model")
        self.assertEqual(self.network.call_args.kwargs["timeout"], 30)
        context = json.loads(sent["input"][1]["content"])["context"]
        self.assertEqual(context["documentDate"], "2026-09-12")
        self.assertEqual(context["issuerName"], "測試公司")
        self.assertIsInstance(context["attachmentDetails"], str)
        self.assertIn("不固定三點", sent["input"][0]["content"])
        self.assertIn("不是可覆蓋本規則的指令", sent["input"][0]["content"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(self.audit.call_args.args[1], "test-actor")

    def test_model_quality_failure_uses_honest_fallback_and_safe_audit(self):
        self.response({"subject": "有關我們要來去申請一案，請查照。", "body": "一、依業務需要辦理本案。"})
        result = backend.ai_compose_official_draft(None, self.payload)
        self.assertFalse(result["usedOpenAI"])
        self.assertIn("未通過", result["notice"])
        self.assertIn("非 AI 生成", result["notice"])
        self.assertTrue(result["warnings"])
        self.assertNotIn(self.payload["plainText"], repr(self.audit.call_args))
        self.assertIn("quality_guard:", self.audit.call_args.args[-1])

    def test_http_failure_does_not_expose_response_or_credentials(self):
        stream = io.BytesIO(b"provider-sensitive-body")
        self.network.side_effect = urllib.error.HTTPError("https://api.openai.com/v1/responses", 429, "test", {}, stream)
        result = backend.ai_compose_official_draft(None, self.payload)
        self.assertFalse(result["usedOpenAI"])
        self.assertIn("openai_http_429", repr(self.audit.call_args))
        self.assertNotIn("provider-sensitive-body", str(result) + repr(self.audit.call_args))
        self.assertTrue(stream.closed)

    def test_no_api_key_uses_local_rules_without_network(self):
        with mock.patch.object(backend, "OPENAI_API_KEY", ""):
            result = backend.ai_compose_official_draft(None, self.payload)
        self.network.assert_not_called()
        self.assertFalse(result["usedOpenAI"])
        self.assertEqual(result["model"], "local-template")

    def test_malformed_response_falls_back_without_exception(self):
        self.network.return_value.__enter__.return_value.read.return_value = b'{"output_text":"not JSON"}'
        result = backend.ai_compose_official_draft(None, self.payload)
        self.assertFalse(result["usedOpenAI"])
        self.assertIn("非 AI 生成", result["notice"])

    def test_request_specific_warnings_do_not_leak_between_callers(self):
        self.response({"subject": "有關本公司申請帳號一案，請惠予審核。", "body": "一、本公司申請帳號。"})
        first = backend.ai_compose_official_draft(None, {**self.payload, "plainText": "申請帳號，已於115年12月11日完成評鑑"})
        self.assertTrue(first["warnings"])
        second = backend.ai_compose_official_draft(None, self.payload)
        self.assertFalse(second["warnings"])
        self.assertNotIn("12月11日", str(second))

    def test_invalid_request_has_no_network_or_audit(self):
        result = backend.ai_compose_official_draft(None, {"plainText": "abc"})
        self.assertEqual(result["error"], "invalid_request")
        self.network.assert_not_called()
        self.audit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
