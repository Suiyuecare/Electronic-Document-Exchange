import assert from "node:assert/strict";
import { spawn, execFile } from "node:child_process";
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";
import { promisify } from "node:util";

const require = createRequire(path.join(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json"));
const { chromium } = require("playwright");
const output = process.env.EDOC_UI_ARTIFACT_DIR || "/tmp/edoc-launch-ui-20260907";
const python = process.env.EDOC_TEST_PYTHON || "python3";
await mkdir(output, { recursive: true });
const fixture = spawn(python, ["tests/support/five_account_browser_fixture.py"], {
  env: { ...process.env, EDOC_BROWSER_ROLE: "ceo" }, stdio: ["pipe", "pipe", "pipe"],
});
const lines = readline.createInterface({ input: fixture.stdout });
let browser;
try {
  const first = await Promise.race([
    new Promise((resolve, reject) => { lines.once("line", resolve); fixture.once("exit", () => reject(new Error("fixture_early_exit"))); }),
    new Promise((_, reject) => setTimeout(() => reject(new Error("fixture_start_timeout")), 30000).unref()),
  ]);
  const { origin, authState } = JSON.parse(first);
  // All identities and credentials belong to the disposable fixture only.
  console.log(JSON.stringify({ fixtureOrigin: origin, productionAccountsUsed: false }));
  const run = promisify(execFile);
  const agentBrowser = process.env.EDOC_AGENT_BROWSER || "agent-browser";
  try {
    await run(agentBrowser, ["--session", "edoc-launch-check", "open", origin]);
    const snapshot = await run(agentBrowser, ["--session", "edoc-launch-check", "snapshot", "-i"]);
    assert.ok(snapshot.stdout.trim(), "agent_browser_blank_page");
    await run(agentBrowser, ["--session", "edoc-launch-check", "screenshot", path.join(output, "entry-check.png")]);
  } finally {
    await run(agentBrowser, ["--session", "edoc-launch-check", "close"]);
  }
  browser = await chromium.launch({ executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", headless: true });
  const results = [];
  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport });
    await context.addInitScript((session) => localStorage.setItem("suiyuecare-edoc-session", JSON.stringify(session)), authState);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", () => errors.push("page_error"));
    // Local browser acceptance must never contact a production application.
    await context.route("**/*", route => {
      const url = new URL(route.request().url());
      if (url.origin === origin || ["data:", "blob:"].includes(url.protocol)) return route.continue();
      return route.abort();
    });
    await page.goto(origin, { waitUntil: "networkidle" });
    await page.waitForSelector("#appShell:not(.hidden)");
    const routes = ["dashboard", "compose", "electronicSeal", "approvalLog", "inbound", "settings"];
    const routeResults = [];
    for (const route of routes) {
      await page.evaluate(target => setView(target), route);
      await page.waitForTimeout(200);
      const state = await page.evaluate(() => ({
        active: document.querySelector(".view.active")?.id,
        overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      }));
      assert.equal(state.active, route, `wrong_active_view_${route}`);
      assert.ok(state.overflow <= 1, `horizontal_overflow_${route}_${viewport.width}`);
      routeResults.push({ requested: route, ...state });
    }
    await page.evaluate(() => {
      setView("accounts");
      // Deliberately mixed statuses exercise UI classification, not backend auth.
      userAccounts.splice(0, userAccounts.length, ...[
        { id: "UI-ENABLED", name: "隔離驗收甲", status: "啟用" },
        { id: "UI-PENDING", name: "隔離驗收乙", status: "待啟用" },
        { id: "UI-INACTIVE", name: "隔離驗收丙", status: "停用" },
      ].map(item => ({ ...item, email: "fixture@example.invalid", role: "員工", unit: "驗收部", title: "職員", provider: "Google Workspace", mfa: "待確認", account_source: "finance" })));
      renderAccounts();
    });
    assert.equal(await page.locator("#accountUserNote").textContent(), "1 人待首次登入 · 1 人停用");
    await page.locator('[data-account-filter="待啟用"]').click();
    assert.equal(await page.locator("#accountRows tr").count(), 1);
    assert.match(await page.locator("#accountRows").textContent(), /隔離驗收乙/);
    if (viewport.width < 600) {
      const search = await page.locator("#accountSearch").boundingBox();
      assert.ok(search.width > 240, "mobile_account_search_squeezed");
    }
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(output, `accounts-${viewport.width}.png`), fullPage: true });
    results.push({ viewport, routeResults, pendingFilter: "pass", errors });
    await context.close();
  }
  console.log(JSON.stringify({ passed: true, results, output, fixtureOnly: true }));
} finally {
  if (browser) await browser.close();
  lines.close();
  fixture.stdin.end("stop\n");
}
