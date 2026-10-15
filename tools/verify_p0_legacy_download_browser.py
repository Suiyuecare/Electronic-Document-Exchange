"""Real-browser regression of the shipping legacy PDF download functions.

Only synthetic files and a synthetic token are used on 127.0.0.1. This focused
harness exercises the actual app.js functions, not full SSO or business ACLs.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.six_role_browser_acceptance import Browser

TOKEN = "isolated-download-test-token-not-a-real-credential"
FILE_BYTES = b"%PDF-1.4\n% isolated synthetic download bytes\n1 0 obj<</Type/Catalog>>endobj\n%%EOF\n"


def function_sources():
    source = (ROOT / "app.js").read_text()
    boundaries = (
        ("function isHeaderSafeToken(", "\nasync function fetchOpsJson("),
        ("async function downloadBinaryFile(", "\nfunction blockOperation("),
        ("async function downloadPdfVersion(", "\nfunction generateSealApplication("),
    )
    return "\n".join(source[source.index(start):source.index(end, source.index(start))] for start, end in boundaries)


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    requests = []
    gate = threading.Event()
    gate.set()
    fixture_script = """
const authState = { token: TOKEN_VALUE };
const backendApiBase = window.location.origin + '/api';
const doc = {id:'synthetic-document',no:'SYNTH-001'};
const pdfVersionStore = {[doc.id]:{before:{url:'/api/files/ok'},after:{url:'/api/files/ok'}}};
const currentDispatchDoc = () => doc;
window.fixture = {audits:[],toasts:[],anchorClicks:[],errors:[]};
function addSealAudit(title,detail){fixture.audits.push({title,detail});}
function showToast(message){fixture.toasts.push(message);document.querySelector('#status').textContent=message;}
window.addEventListener('error',e=>fixture.errors.push(e.message));
window.addEventListener('unhandledrejection',e=>fixture.errors.push(String(e.reason)));
const realAnchorClick = HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click = function(){fixture.anchorClicks.push({href:this.href,download:this.download});return realAnchorClick.call(this);};
function setupCase(kind,url){
 fixture.audits=[];fixture.toasts=[];fixture.anchorClicks=[];
 document.querySelector('#status').textContent='';
 pdfVersionStore[doc.id][kind]={url};
}
FUNCTION_SOURCES
document.querySelector('#downloadBeforePdfBtn').addEventListener('click',()=>downloadPdfVersion('before'));
document.querySelector('#downloadAfterPdfBtn').addEventListener('click',()=>downloadPdfVersion('after'));
""".replace("TOKEN_VALUE", json.dumps(TOKEN)).replace("FUNCTION_SOURCES", function_sources())
    html = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>隔離下載驗收</title><link rel="stylesheet" href="/styles.css"><style>main{max-width:680px;margin:24px auto;padding:20px}h1{font-size:24px}.fixture-actions{display:flex;gap:12px;flex-wrap:wrap}#status{min-height:72px;margin-top:20px;overflow-wrap:anywhere}</style></head><body><main class="panel"><h1>PDF 版本下載｜隔離驗收</h1><p>合成文件，不連正式服務。</p><div class="fixture-actions"><button class="secondary-button" id="downloadBeforePdfBtn" type="button">下載押章前</button><button class="primary-button" id="downloadAfterPdfBtn" type="button">下載押章後</button></div><div id="status" role="status"></div></main><script src="/fixture.js"></script></body></html>""".encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/":
                return self.send_bytes(200, html, "text/html; charset=utf-8")
            if parsed.path == "/fixture.js":
                return self.send_bytes(200, fixture_script.encode(), "text/javascript")
            if parsed.path == "/styles.css":
                return self.send_bytes(200, (ROOT / "styles.css").read_bytes(), "text/css")
            if parsed.path.startswith("/assets/fonts/"):
                return self.send_bytes(404, b"", "text/plain")
            if parsed.path.startswith("/api/") or parsed.path == "/external-sink":
                row = {"path": parsed.path, "case": query.get("case", [""])[0],
                       "authorization_present": bool(self.headers.get("Authorization")),
                       "authorization_matches_synthetic": self.headers.get("Authorization") == "Bearer " + TOKEN,
                       "origin_port": self.server.server_port}
                requests.append(row)
                if parsed.path == "/api/files/slow":
                    gate.wait(timeout=15)
                if parsed.path == "/api/files/denied":
                    return self.send_bytes(403, b'{"error":"synthetic_access_denied"}', "application/json")
                if parsed.path == "/api/files/redirect":
                    self.send_response(302)
                    self.send_header("Location", self.server.sink_origin + "/external-sink")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if not row["authorization_matches_synthetic"]:
                    return self.send_bytes(401, b"synthetic_auth_required", "text/plain")
                filename = query.get("name", ["synthetic.pdf"])[0]
                return self.send_bytes(200, FILE_BYTES, "application/pdf", filename)
            return self.send_bytes(404, b"", "text/plain")

        def send_bytes(self, status, data, content_type, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(data)

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    origin = f"http://127.0.0.1:{servers[0].server_port}"
    sink_origin = f"http://127.0.0.1:{servers[1].server_port}"
    servers[0].sink_origin = sink_origin
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in servers]
    for thread in threads:
        thread.start()
    report = {"scope":"synthetic_localhost_shipping_function_browser", "rows":[],
              "real_sso_tested":False,"production_called":False,"full_application_layout_tested":False,
              "source_app_sha256":hashlib.sha256((ROOT / "app.js").read_bytes()).hexdigest()}
    with tempfile.TemporaryDirectory(prefix="edoc-legacy-download-browser-") as temporary:
        temp = Path(temporary)
        downloads = temp / "downloads"
        downloads.mkdir()
        config = temp / "browser.json"
        config.write_text(json.dumps({"allowedDomains":["127.0.0.1"],"headed":False,"downloadPath":str(downloads)}))
        browser = Browser(config, session="dl-" + str(os.getpid()), namespace="edoc-p0")

        def require(value, code):
            if not value:
                raise AssertionError(code)

        def wait_file(name):
            path = downloads / name
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if path.is_file() and path.read_bytes() == FILE_BYTES:
                    return hashlib.sha256(path.read_bytes()).hexdigest()
                time.sleep(0.05)
            raise AssertionError("real_browser_download_missing_or_bytes_mismatch:" + name)

        def setup(kind, url):
            browser.evaluate("setupCase(" + json.dumps(kind) + "," + json.dumps(url) + ");true")

        def state(kind):
            identity = "downloadBeforePdfBtn" if kind == "before" else "downloadAfterPdfBtn"
            return browser.evaluate("(()=>{const b=document.getElementById(" + json.dumps(identity) + ");return {audits:fixture.audits.length,toasts:fixture.toasts.length,anchorClicks:fixture.anchorClicks.length,errors:fixture.errors,disabled:b.disabled,busy:b.getAttribute('aria-busy'),url:location.href,overflow:document.documentElement.scrollWidth>innerWidth+1,buttonWidth:b.getBoundingClientRect().width,buttonHeight:b.getBoundingClientRect().height}})()")

        try:
            for device, dimensions in (("desktop", (1440, 1000)), ("mobile", (390, 844))):
                browser.run("set", "viewport", *map(str, dimensions))
                browser.run("open", origin)
                browser.until("typeof downloadPdfVersion==='function'")
                rows = []
                for kind in ("before", "after"):
                    name = f"{device}-{kind}-authorized.pdf"
                    case = f"{device}-{kind}-authorized"
                    setup(kind, f"/api/files/ok?case={case}&name={name}")
                    selector = "#downloadBeforePdfBtn" if kind == "before" else "#downloadAfterPdfBtn"
                    browser.run("click", selector)
                    digest = wait_file(name)
                    browser.until("fixture.audits.length===1")
                    check = state(kind)
                    hits = [r for r in requests if r["case"] == case]
                    require(len(hits) == 1 and hits[0]["authorization_matches_synthetic"], "success_bearer_missing")
                    require(check["anchorClicks"] == 1 and not check["disabled"] and not check["busy"], "success_state_invalid")
                    rows.append({"case":kind+"_200","passed":True,"file_sha256":digest,"request_count":1,"bearer_matched":True})

                case = device + "-denied"
                before_files = sorted(p.name for p in downloads.iterdir())
                setup("after", f"/api/files/denied?case={case}")
                browser.run("click", "#downloadAfterPdfBtn")
                browser.until("fixture.toasts.length===1")
                check = state("after")
                require(check["audits"] == 0 and check["anchorClicks"] == 0 and not check["disabled"] and not check["busy"], "denied_false_success")
                require(before_files == sorted(p.name for p in downloads.iterdir()), "denied_downloaded_file")
                require(check["url"] == origin + "/", "denied_navigated_away")
                browser.run("screenshot", str(output / f"{device}-403.png"))
                rows.append({"case":"403","passed":True,"no_download":True,"no_success_audit":True,"button_recovered":True})

                case = device + "-slow"
                name = case + ".pdf"
                setup("before", f"/api/files/slow?case={case}&name={name}")
                idle = state("before")
                gate.clear()
                browser.run("click", "#downloadBeforePdfBtn")
                browser.until("document.querySelector('#downloadBeforePdfBtn').disabled")
                browser.evaluate("document.querySelector('#downloadBeforePdfBtn').click();downloadPdfVersion('before');true")
                pending = state("before")
                require(pending["disabled"] and pending["busy"] == "true" and pending["audits"] == 0, "pending_state_invalid")
                require(pending["buttonWidth"] == idle["buttonWidth"] and pending["buttonHeight"] == idle["buttonHeight"], "pending_button_layout_shift")
                browser.run("screenshot", str(output / f"{device}-slow.png"))
                gate.set()
                wait_file(name)
                browser.until("fixture.audits.length===1&&!document.querySelector('#downloadBeforePdfBtn').disabled")
                hits = [r for r in requests if r["case"] == case]
                require(len(hits) == 1, "duplicate_slow_requests")
                require(state("before")["anchorClicks"] == 1, "duplicate_slow_downloads")
                rows.append({"case":"slow_duplicate","passed":True,"request_count":1,"busy_observed":True,"button_dimensions_preserved":True})

                blob_url = browser.evaluate("URL.createObjectURL(new Blob([new Uint8Array(" + json.dumps(list(FILE_BYTES)) + ")],{type:'application/pdf'}))")
                setup("after", blob_url)
                request_count = len(requests)
                browser.run("click", "#downloadAfterPdfBtn")
                digest = wait_file("SYNTH-001-after-seal.pdf")
                browser.until("fixture.audits.length===1")
                require(len(requests) == request_count and state("after")["anchorClicks"] == 1, "blob_used_network")
                (downloads / "SYNTH-001-after-seal.pdf").unlink()
                browser.evaluate("URL.revokeObjectURL(" + json.dumps(blob_url) + ");true")
                rows.append({"case":"same_origin_blob","passed":True,"file_sha256":digest,"api_requests":0})

                for label, url in (("cross_origin",sink_origin+"/external-sink"),("protocol_relative",sink_origin.replace("http:","")+"/external-sink"),("foreign_blob","blob:"+sink_origin+"/synthetic"),("https_external","https://outside.invalid/private.pdf")):
                    setup("before", url)
                    request_count = len(requests)
                    browser.run("click", "#downloadBeforePdfBtn")
                    browser.until("fixture.toasts.length===1")
                    check = state("before")
                    require(len(requests) == request_count and check["anchorClicks"] == 0 and check["audits"] == 0, "external_download_not_blocked:" + label)
                    rows.append({"case":label,"passed":True,"network_requests":0,"no_success_audit":True})

                case = device + "-redirect"
                setup("before", "/api/files/redirect?case=" + case)
                request_count = len(requests)
                browser.run("click", "#downloadBeforePdfBtn")
                browser.until("fixture.toasts.length===1")
                check = state("before")
                hits = requests[request_count:]
                require(len(hits) == 1 and hits[0]["path"] == "/api/files/redirect", "redirect_followed")
                require(check["audits"] == 0 and check["anchorClicks"] == 0, "redirect_false_success")
                require(not check["errors"] and not check["overflow"], "browser_error_or_harness_overflow")
                rows.append({"case":"cross_origin_302","passed":True,"redirect_followed":False,"no_success_audit":True})
                report["rows"].append({"device":device,"viewport":dimensions,"cases":rows,"passed":True})
        finally:
            gate.set()
            try:
                browser.run("close")
            except RuntimeError:
                pass
            finally:
                for server in servers:
                    server.shutdown()
                    server.server_close()
                for thread in threads:
                    thread.join(timeout=5)
    report["requests"] = requests
    report["passed"] = len(report["rows"]) == 2 and all(row["passed"] for row in report["rows"])
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({"passed":result["passed"],"devices":[{"device":r["device"],"cases":len(r["cases"])} for r in result["rows"]]}, ensure_ascii=False))
