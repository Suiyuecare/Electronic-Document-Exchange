from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DeploymentRunbookContractTest(unittest.TestCase):
    def test_project_link_is_scoped_and_uses_actual_project_name(self):
        doc = (ROOT / "docs/deployment-production.md").read_text(encoding="utf-8")
        self.assertIn(
            'vercel link --yes --project electronic-document-exchange --scope "$VERCEL_SCOPE"',
            doc,
        )
        self.assertNotIn("vercel link --yes --project Electronic-Document-Exchange", doc)
        self.assertLess(doc.index("vercel whoami"), doc.index("vercel link --yes"))
        for command in ("vercel env add", "vercel pull", "vercel build", "vercel deploy", "vercel rollback"):
            lines = [line for line in doc.splitlines() if line.startswith(command + " ")]
            self.assertTrue(lines)
            self.assertTrue(all('--scope "$VERCEL_SCOPE"' in line for line in lines))

    def test_internal_launch_does_not_require_unapproved_formal_providers(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        section = readme.split("## GitHub / Vercel / Supabase 串接", 1)[1]
        section = section.split("PDF 與檔案儲存：", 1)[0]
        self.assertIn("Email／LINE 為選配", section)
        self.assertIn("另待規格驗收與人工核准", section)
        self.assertNotIn("EDOC_SIGNATURE_API_KEY=", section)
        self.assertNotIn("EDOC_TSA_API_KEY=", section)
        self.assertNotIn("HTTPS credential 仍需更新", section)

    def test_pdf_policy_is_consistent_with_image_scanning(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        doc = (ROOT / "docs/deployment-production.md").read_text(encoding="utf-8")
        self.assertNotIn("V2 preflight 目前採同步", readme)
        self.assertIn("圖片仍需可用且已核准的掃描 provider", readme)
        self.assertIn("同步完成前仍禁止送簽與切換案件", readme)
        self.assertIn("圖片另須通過掃毒", doc)
        self.assertIn("結構預檢並明確記錄為 `not_scanned`", doc)


if __name__ == "__main__":
    unittest.main()
