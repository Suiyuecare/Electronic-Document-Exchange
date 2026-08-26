import { createRequire } from "node:module";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const require = createRequire(
  path.join(
    os.homedir(),
    ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/package.json",
  ),
);
const { chromium } = require("playwright");

const baseUrl = process.env.EDOC_AUDIT_BASE_URL || "http://127.0.0.1:5175";
const email = process.env.EDOC_AUDIT_EMAIL || "";
const password = process.env.EDOC_AUDIT_PASSWORD || "";
const outputPath = process.env.EDOC_AUDIT_OUTPUT || "/tmp/edoc-authorized-ui-audit.json";

if (!email || !password) {
  throw new Error("Set EDOC_AUDIT_EMAIL and EDOC_AUDIT_PASSWORD for a local fixture account.");
}

const loginResponse = await fetch(`${baseUrl}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email, password, provider: "Automated UI audit" }),
});
if (!loginResponse.ok) {
  throw new Error(`Fixture login failed: ${loginResponse.status}`);
}
const session = await loginResponse.json();

const browser = await chromium.launch({
  executablePath: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});

const results = [];
for (const viewport of [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "mobile", width: 390, height: 844 },
]) {
  const context = await browser.newContext({ viewport });
  await context.addInitScript((value) => {
    window.localStorage.setItem("suiyuecare-edoc-session", JSON.stringify(value));
  }, session);
  const page = await context.newPage();
  const requestFailures = [];
  const errorResponses = [];
  const consoleErrors = [];
  page.on("requestfailed", (request) => {
    requestFailures.push({ url: request.url(), reason: request.failure()?.errorText || "failed" });
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const url = new URL(response.url());
    errorResponses.push({ status: response.status(), path: url.pathname });
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.waitForSelector("#appShell:not(.hidden)", { timeout: 10000 });
  // Local fixture hosts do not receive the production go-live decision. Audit
  // the actual internal-launch UX: formal government exchange stays hidden
  // unless the backend explicitly reports formalGo=true.
  await page.evaluate(() => {
    goLiveAuditState = {
      formalGo: false,
      summary: "內部正式使用；政府電子交換未啟用。",
    };
    applyFormalExchangeUiState();
  });
  const routes = await page.evaluate(() => allowedRoutesForRole());
  const dashboard = await page.evaluate(() => {
    setView("dashboard");
    renderRoleDashboard();
    return {
      metrics: [1, 2, 3, 4].map((position) => ({
        label: document.querySelector(`#dashboardMetricLabel${position}`)?.textContent?.trim() || "",
        value: document.querySelector(`#dashboardMetricValue${position}`)?.textContent?.trim() || "",
        note: document.querySelector(`#dashboardMetricNote${position}`)?.textContent?.trim() || "",
      })),
      pipeline: [...document.querySelectorAll("#dashboardPipeline > div")].map((item) => item.textContent.trim()),
      moreRoutes: secondaryRoutesForRole(activeRole()).filter((route) => isRouteAllowed(route)),
    };
  });
  const pages = [];
  for (const route of routes) {
    await page.evaluate((target) => setView(target), route);
    await page.waitForTimeout(350);
    pages.push(await page.evaluate(({ target, mobile }) => {
      const activeView = document.querySelector(".view.active");
      const root = activeView || document.documentElement;
      const allControls = [...root.querySelectorAll("button, a[href], input:not([type=hidden]), select, textarea, [role=button]")]
        .filter((element) => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
        });
      const undersized = mobile
        ? allControls.filter((element) => {
          if (element.matches("input[type=checkbox], input[type=radio]")) return false;
          const rect = element.getBoundingClientRect();
          return rect.height < 44 || rect.width < 44;
        }).map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName.toLowerCase(),
            id: element.id || "",
            className: String(element.className || "").slice(0, 100),
            text: String(element.getAttribute("aria-label") || element.textContent || element.value || "").trim().slice(0, 80),
            width: Math.round(rect.width),
            height: Math.round(rect.height),
          };
        })
        : [];
      return {
        requestedRoute: target,
        activeRoute: document.body.dataset.activeRoute,
        activeView: activeView?.id || "",
        title: document.querySelector("#pageTitle")?.textContent?.trim() || "",
        documentOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        viewOverflowX: root.scrollWidth - root.clientWidth,
        undersized,
      };
    }, { target: route, mobile: viewport.name === "mobile" }));
  }
  results.push({
    viewport,
    role: session.user?.role || "",
    routes,
    dashboard,
    pages,
    requestFailures,
    errorResponses,
    consoleErrors,
  });
  await context.close();
}

await browser.close();
await fs.writeFile(outputPath, `${JSON.stringify(results, null, 2)}\n`, "utf8");
console.log(JSON.stringify({
  outputPath,
  viewports: results.map((result) => ({
    name: result.viewport.name,
    routes: result.routes.length,
    overflowPages: result.pages.filter((page) => page.documentOverflowX > 1 || page.viewOverflowX > 1).map((page) => page.requestedRoute),
    undersized: result.pages.flatMap((page) => page.undersized.map((control) => ({ route: page.requestedRoute, ...control }))),
    requestFailures: result.requestFailures.length,
    errorResponses: result.errorResponses,
    consoleErrors: result.consoleErrors.length,
  })),
}, null, 2));
