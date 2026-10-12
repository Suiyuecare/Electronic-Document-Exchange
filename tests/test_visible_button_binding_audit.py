"""Synthetic audit evidence only: no browser click or functional attestation."""
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from tools import visible_button_binding_audit as audit


class VisibleButtonBindingAuditTest(unittest.TestCase):
    def root(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        root.chmod(0o700)
        return root

    def test_repository_and_repository_alias_output_rejected_before_fixture(self):
        root = self.root(); alias = root/"repo-alias"; alias.symlink_to(audit.ROOT, target_is_directory=True)
        with mock.patch.object(audit.Fixture, "setUpClass") as setup:
            for output in (audit.ROOT, audit.ROOT/"must-not-create", alias):
                with self.subTest(output=output.name), self.assertRaises((ValueError, OSError)):
                    audit.run(output)
            setup.assert_not_called()
        self.assertFalse((audit.ROOT/"must-not-create").exists())

    def test_existing_report_symlink_and_hardlink_never_overwrite_victim(self):
        root = self.root(); victim = root/"victim"; victim.write_bytes(b"preserve original"); victim.chmod(0o600)
        for kind in ("symlink", "hardlink"):
            folder = root/kind; folder.mkdir(mode=0o700)
            if kind == "symlink": (folder/"report.json").symlink_to(victim)
            else: os.link(victim, folder/"report.json")
            with mock.patch.object(audit.Fixture, "setUpClass") as setup, self.subTest(kind=kind):
                with self.assertRaisesRegex(ValueError, "link_or_permissions"):
                    audit.run(folder)
                setup.assert_not_called()
            self.assertEqual(b"preserve original", victim.read_bytes())

    def test_existing_regular_report_and_public_directory_are_not_silently_reused(self):
        root = self.root(); folder = root/"old"; folder.mkdir(mode=0o700)
        report = folder/"report.json"; report.write_bytes(b"previous audit"); report.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "already_exists"):
            audit.ReportOutput(folder)
        self.assertEqual(b"previous audit", report.read_bytes())
        public = root/"public"; public.mkdir(); public.chmod(0o755)
        with self.assertRaisesRegex(ValueError, "private_owned"):
            audit.ReportOutput(public)

    def test_atomic_report_update_is_private_and_detects_replaced_inode(self):
        root = self.root()
        with audit.ReportOutput(root/"new") as output:
            output.write({"stage": "one"}); output.write({"stage": "two"})
            report = output.path/"report.json"
            self.assertEqual({"stage": "two"}, json.loads(report.read_bytes()))
            self.assertEqual(0, output.path.stat().st_mode & 0o077)
            self.assertEqual(0, report.stat().st_mode & 0o077)
            old = output.path/"old-inode"; report.rename(old)
            report.write_bytes(b"foreign replacement"); report.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "report_changed"):
                output.write({"stage": "must not overwrite"})
            self.assertEqual(b"foreign replacement", report.read_bytes())

    def test_loopback_and_browser_transport_abort_non_fixture_network(self):
        with audit.loopback_only(), socket.socket() as sock:
            for address in (("192.0.2.1", 443), ("example.invalid", 443)):
                with self.assertRaisesRegex(PermissionError, "external_network_forbidden"):
                    sock.connect(address)
            with self.assertRaises(PermissionError): socket.getaddrinfo("example.invalid", 443)
        for origin in ("https://127.0.0.1:9999", "http://example.invalid:9999", "http://127.0.0.1.evil:9999"):
            with self.assertRaises(ValueError): audit.require_local_origin(origin)
        audit.require_local_origin("http://127.0.0.1:9999")
        self.assertIn("route.abort()", audit.BRIDGE)
        self.assertIn("new URL(args[0]).origin!==origin", audit.BRIDGE)

    def script_rows(self, setup=""):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node required for event-owner audit contract")
        instrument = audit.INSTRUMENT.replace("<script>", "").replace("</script>", "")
        script = r"""
const vm=require('node:vm');
class Element extends EventTarget {
 constructor(id,tag='BUTTON'){super();this.id=id;this.tagName=tag;this.type='button';this.parentNode=null;this.form=null;this.disabled=false;this.attrs={};this.hidden=false;this.inert=false;}
 getClientRects(){return this.hidden?[]:[{}]}
 getAttribute(name){return this.attrs[name]??null}
 hasAttribute(name){return Object.hasOwn(this.attrs,name)}
 matches(selector){return selector===':disabled'&&!!this.disabledByFieldset}
 closest(selector){return selector==='[inert]'&&this.inert?this:null}
}
const window=new EventTarget(),document=new EventTarget(),container=new Element('container','DIV'),button=new Element('plain'),targets={};
container.parentNode=document;button.parentNode=container;
const page={id:'synthetic-route',querySelectorAll:()=>[button]};
document.querySelector=()=>page;document.querySelectorAll=()=>[];document.getElementById=id=>targets[id]||null;
const context=vm.createContext({EventTarget,window,document,getComputedStyle:()=>({visibility:'visible'}),AbortController,Event});
vm.runInContext(INSTRUMENT,context);
SETUP
console.log(JSON.stringify(vm.runInContext(AUDIT,context)));
""".replace("INSTRUMENT", json.dumps(instrument)).replace("SETUP", setup).replace("AUDIT", json.dumps(audit.AUDIT))
        result = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["rows"]

    def test_ancestor_listener_is_candidate_not_direct_or_selector_proof(self):
        rows = self.script_rows("document.addEventListener('click',()=>{});")
        self.assertFalse(rows[0]["directClick"])
        self.assertEqual(["document"], rows[0]["delegatedClickOwners"])
        self.assertEqual("delegation_candidate_only", rows[0]["classification"])

    def test_persistent_direct_and_once_lifecycle_have_distinct_classification(self):
        self.assertEqual("direct_or_native", self.script_rows("button.addEventListener('click',()=>{});")[0]["classification"])
        rows = self.script_rows("button.addEventListener('click',()=>{}, {once:true});button.dispatchEvent(new Event('click'));")
        self.assertFalse(rows[0]["directClick"])
        self.assertEqual(["button"], rows[0]["unknownClickLifecycleOwners"])
        self.assertEqual("unknown_lifecycle_candidate_only", rows[0]["classification"])

    def test_aborted_or_removed_listener_is_not_observed_active_owner(self):
        for setup in (
            "const controller=new AbortController();button.addEventListener('click',()=>{}, {signal:controller.signal});controller.abort();",
            "const callback=()=>{};button.addEventListener('click',callback);button.removeEventListener('click',callback);",
        ):
            with self.subTest(setup=setup):
                self.assertEqual("no_observed_owner", self.script_rows(setup)[0]["classification"])

    def test_popover_requires_real_attribute_methods_and_supported_action(self):
        prefix = "const target=new Element('popover','DIV');targets.popover=target;button.attrs.popovertarget='popover';"
        self.assertFalse(self.script_rows(prefix)[0]["nativePopover"])
        valid = prefix+"target.attrs.popover='auto';target.showPopover=()=>{};target.hidePopover=()=>{};"
        self.assertTrue(self.script_rows(valid)[0]["nativePopover"])
        self.assertFalse(self.script_rows(valid+"button.attrs.popovertargetaction='unsupported';")[0]["nativePopover"])

    def test_hidden_disabled_and_unsafe_identifier_are_not_overclaimed(self):
        for setup in ("button.hidden=true;", "button.disabled=true;", "button.disabledByFieldset=true;", "button.inert=true;"):
            with self.subTest(setup=setup): self.assertEqual([], self.script_rows(setup))
        self.assertEqual("anonymous-button-1", self.script_rows("button.id='private@example.invalid';")[0]["id"])

    def test_report_is_not_sso_device_selector_functional_or_release_attestation(self):
        class Browser:
            def __init__(self, origin): self.calls=[]
            def run(self, *args):
                self.calls.append(args)
                if args[0] in {"click", "fill", "upload", "press"}: raise AssertionError("mutation command forbidden")
            def until(self, *_args, **_kwargs): pass
            def evaluate(self, script):
                if script == audit.AUDIT:
                    return {"activeRoute": "dashboard", "visibleEnabledButtonCount": 1, "errorCount": 0,
                        "rows": [{"id": "synthetic-button", "type": "button", "classification": "delegation_candidate_only"}]}
                return True
        root = self.root()
        with mock.patch.object(audit.Fixture, "setUpClass"), mock.patch.object(audit.Fixture, "tearDownClass") as cleanup, \
                mock.patch.object(audit.Fixture, "origin", "http://127.0.0.1:9999", create=True), \
                mock.patch.object(audit.transport, "LocalPlaywrightBrowser", Browser), \
                mock.patch.object(audit, "isolated_browser_session", return_value={"token": "synthetic-private-session"}), \
                mock.patch.object(audit, "BROWSER_ROLES", ("staff",)), mock.patch.object(audit, "ROUTES", ("dashboard",)), \
                mock.patch.object(audit, "source_digest", return_value="a"*64), \
                mock.patch.object(audit.subprocess, "run", return_value=mock.Mock(stdout="b"*40)), \
                mock.patch("sys.stdout", new=io.StringIO()):
            report = audit.run(root/"audit")
        cleanup.assert_called_once()
        for key in ("functional_click_coverage", "static_audit_superseded", "real_human_sso_verified", "physical_device_verified",
                    "external_requests_allowed", "mutating_buttons_clicked", "listener_callbacks_wrapped", "production_accounts_changed", "promotion_authorized"):
            self.assertIs(report[key], False)
        self.assertTrue(report["delegation_is_only_candidate_not_selector_proof"])
        self.assertTrue(report["unknown_listener_lifecycle_is_not_active_owner"])
        self.assertEqual("DISABLED", report["government_exchange"])
        self.assertEqual(1, report["totals"]["delegation_candidate_only"])
        self.assertNotIn("synthetic-private-session", (root/"audit/report.json").read_text())


if __name__ == "__main__":
    unittest.main()
