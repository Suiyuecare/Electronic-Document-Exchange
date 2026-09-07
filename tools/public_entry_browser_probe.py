"""Read-only public eDoc loader timing; no credentials, auth injection or SSO.

Only anonymous navigation is measured. An authenticated usable time is never
claimed from this probe. Its dedicated session is always closed on completion.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile
import time

from six_role_browser_acceptance import Browser

PROBE = """(()=>{
 if(location.hostname!=='edoc.suiyuecare.com'||location.pathname!=='/')return;
 const sample={loaderVisibleMs:null,authenticatedUsableMs:null,pageHideMs:null,origin:'edoc',auth:'anonymous'};
 const save=()=>{sessionStorage.setItem('edoc-public-loader-probe',JSON.stringify(sample));};
 const visible=e=>!!e&&e.getBoundingClientRect().width>0&&getComputedStyle(e).visibility!=='hidden';
 const frame=()=>{const e=document.querySelector('#moduleEntryProgress');if(sample.loaderVisibleMs===null&&visible(e)){sample.loaderVisibleMs=performance.now();save();}if(performance.now()<30000)requestAnimationFrame(frame)};
 addEventListener('pagehide',()=>{sample.pageHideMs=performance.now();save()});save();requestAnimationFrame(frame);
})()"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("tests/.artifacts/public-loader-probe"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {"realLoginPerformed": False, "authenticatedUsableVerified": False, "samples": []}
    with tempfile.TemporaryDirectory(prefix="edoc-public-loader-") as temporary:
        root = Path(temporary)
        config = root / "agent-browser.json"
        config.write_text(json.dumps({"headed": False}))
        script = root / "public-probe.js"
        script.write_text(PROBE)
        browser = Browser(config, session="edoc-entry-0908", namespace="edoc-entry-isolated")
        try:
            for phase in ("cold", "warm"):
                if phase == "cold":
                    browser.run("open", "https://edoc.suiyuecare.com/", "--init-script", str(script))
                    browser.run("set", "viewport", "1440", "1000")
                else:
                    browser.run("open", "https://edoc.suiyuecare.com/")
                time.sleep(2)
                destination = browser.evaluate("({host:location.hostname,path:location.pathname})")
                browser.run("screenshot", str(args.output / f"{phase}-anonymous.png"))
                # Return only to a public static asset to read our own timing
                # key from this fresh origin; no application storage is read.
                browser.run("open", "https://edoc.suiyuecare.com/assets/favicon-32.png")
                timing = browser.evaluate("JSON.parse(sessionStorage.getItem('edoc-public-loader-probe')||'null')")
                report["samples"].append({"phase": phase, "destination": destination, "timing": timing})
            (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False))
        finally:
            browser.run("close")


if __name__ == "__main__":
    main()
