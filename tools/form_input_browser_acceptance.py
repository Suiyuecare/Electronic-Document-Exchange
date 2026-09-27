"""Desktop/mobile committed-input QA on synthetic localhost HTTP fixtures.

Composition/input DOM events exercise actual event handlers, not an OS-native
IME. No hosted service, real employee data or government exchange is contacted.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.editor_race_browser_acceptance import Journey, run
from tools.six_role_browser_acceptance import AUDIT_JS


COMPOSE_PROBE = r'''(()=>{
 window.__inputQA={writes:0,previews:[],scope:'DOM composition events only'};
 const originalSet=Storage.prototype.setItem;
 Storage.prototype.setItem=function(key,value){if(key===composeAutosaveStorageKey)window.__inputQA.writes++;return originalSet.call(this,key,value)};
 const originalPreview=renderOfficialDraftPagesHtml;
 renderOfficialDraftPagesHtml=function(...args){const start=performance.now();const result=originalPreview(...args);window.__inputQA.previews.push(performance.now()-start);return result};
 return true;
})()'''


def navigate(browser, route):
    if browser.evaluate("innerWidth<768&&!document.body.classList.contains('mobile-navigation-open')"):
        browser.click_visible('#mobileMenuButton')
        browser.until("Math.abs(document.querySelector('#primarySidebar').getBoundingClientRect().left)<0.5")
    browser.click_visible(f'.sidebar .nav-item[data-target="{route}"]')
    browser.until("document.querySelector('.view.active')?.id===" + repr(route))


def committed_input_journey(self):
    checks, evidence = {}, {'compositionInputScope': 'DOM events, not OS-native IME', 'devices': {}}
    for browser, device, width, height in [(self.a, 'desktop', 1440, 1000), (self.b, 'mobile', 390, 844)]:
        self.login(browser, width=width, height=height)
        navigate(browser, 'compose')
        browser.until("document.querySelector('#composeCompanySelect').options.length>0&&!!document.querySelector('#composeStepper [data-compose-step]')")
        browser.evaluate(COMPOSE_PROBE)
        paused = browser.evaluate(r'''(async()=>{
          window.__raceRequests.length=0;
          const field=document.querySelector('#subject');field.focus();
          field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          field.value='合成組字部分';field.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText'}));
          await new Promise(resolve=>setTimeout(resolve,2400));
          return {cloudPuts:window.__raceRequests.filter(r=>r.method==='PUT'&&r.path.startsWith('/api/compose-drafts/')).length,
            localWrites:window.__inputQA.writes,previews:window.__inputQA.previews.length,
            saveBlocked:flushComposeInputUpdates()===false,focusRetained:document.activeElement===field};
        })()''')
        checks[device + 'PausedComposeImeNotPersisted'] = paused['cloudPuts'] == paused['localWrites'] == paused['previews'] == 0 and paused['saveBlocked']
        committed = browser.evaluate(r'''(async()=>{
          const field=document.querySelector('#subject');field.value='合成已完成公文主旨';
          field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:field.value}));
          field.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false,inputType:'insertText'}));
          await new Promise(resolve=>setTimeout(resolve,2300));
          return {cloudPuts:window.__raceRequests.filter(r=>r.method==='PUT'&&r.path.startsWith('/api/compose-drafts/')).length,
            previews:window.__inputQA.previews.length,focusRetained:document.activeElement===field,
            savedValue:JSON.parse(localStorage.getItem(composeAutosaveStorageKey)).snapshot.values['#subject'],
            cloudId:composeCloudDraftId,previewDurationsMs:window.__inputQA.previews};
        })()''')
        checks[device + 'ComposeCommittedOnce'] = committed['cloudPuts'] == committed['previews'] == 1 and committed['savedValue'] == '合成已完成公文主旨'
        checks[device + 'ComposeInputFocusRetained'] = paused['focusRetained'] and committed['focusRetained']
        cloud = self.fixture._expect_json('GET', '/api/compose-drafts', 200, token=self.auth['token'])
        checks[device + 'ComposeActualCloudReadback'] = any(row['id'] == committed['cloudId'] and row['snapshot']['values']['#subject'] == '合成已完成公文主旨' for row in cloud)
        burst = browser.evaluate(r'''(async()=>{
          window.__raceRequests.length=0;window.__inputQA.writes=0;window.__inputQA.previews=[];
          const field=document.querySelector('#subject');field.focus();const start=performance.now();
          for(let n=0;n<20;n++){field.value='合成連續輸入 '+n;field.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false,inputType:'insertText'}));}
          const synchronousInputMs=performance.now()-start;await new Promise(resolve=>setTimeout(resolve,2300));
          return {cloudPuts:window.__raceRequests.filter(r=>r.method==='PUT'&&r.path.startsWith('/api/compose-drafts/')).length,
            previews:window.__inputQA.previews.length,localWrites:window.__inputQA.writes,synchronousInputMs,
            latestValue:JSON.parse(localStorage.getItem(composeAutosaveStorageKey)).snapshot.values['#subject'],focusRetained:document.activeElement===field};
        })()''')
        checks[device + 'OrdinaryBurstCoalesced'] = burst['cloudPuts'] == burst['previews'] == 1 and burst['latestValue'] == '合成連續輸入 19' and burst['focusRetained']
        stable = browser.evaluate(r'''(()=>{
          const tab=document.querySelector('#composeStepper [data-compose-step]'),option=document.querySelector('#composeCompanySelect option');
          tab.focus();renderComposeStepper();renderComposeCompanyOptions();renderComposeStepper();renderComposeCompanyOptions();
          return {tabRetained:tab.isConnected&&document.activeElement===tab,optionRetained:option.isConnected};
        })()''')
        checks[device + 'ComposeStableTabAndOptions'] = stable['tabRetained'] and stable['optionRetained']
        compose_layout = browser.evaluate(AUDIT_JS)
        checks[device + 'ComposeNoOverflowOrErrors'] = not compose_layout['overflow'] and not compose_layout['errors']
        browser.run('screenshot', str(self.output / (device + '-compose-committed.png')), '--full')
        navigate(browser, 'electronicSeal')
        document_id = self.upload(browser, device + '-form-input')
        self.expose_fields(browser)
        application = browser.evaluate(r'''(async()=>{
          window.__raceRequests.length=0;const field=document.querySelector('#uploadedSealReason');field.focus();
          field.dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}));
          field.value='合成申請原因組字中';field.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:true,inputType:'insertCompositionText'}));
          await new Promise(resolve=>setTimeout(resolve,2400));
          const applicationPath='/api/official-documents/'+uploadedSealEditorRuntime.documentId;
          const during=window.__raceRequests.filter(r=>r.method==='PATCH'&&r.path===applicationPath).length;
          field.value='合成申請原因已完成';field.dispatchEvent(new CompositionEvent('compositionend',{bubbles:true,data:field.value}));
          field.dispatchEvent(new InputEvent('input',{bubbles:true,isComposing:false,inputType:'insertText'}));
          await new Promise(resolve=>setTimeout(resolve,2300));
          return {patchesDuringComposition:during,patchesAfterCommit:window.__raceRequests.filter(r=>r.method==='PATCH'&&r.path===applicationPath).length,
            focusRetained:document.activeElement===field,dirty:uploadedSealApplicationHasUnsavedChanges()};
        })().catch(error=>({qaError:error.name+':'+error.message}))''')
        if 'qaError' in application:
            return self.finish('committed-form-input-application-error', browser, {'applicationProbeCompleted': False}, {'qaErrorType': application['qaError'].split(':', 1)[0], 'device': device})
        checks[device + 'ApplicationPausedImeNotPersisted'] = application['patchesDuringComposition'] == 0
        checks[device + 'ApplicationCommittedOnce'] = application['patchesAfterCommit'] == 1 and not application['dirty']
        checks[device + 'ApplicationFocusRetained'] = application['focusRetained']
        checks[device + 'ApplicationActualReadback'] = self.detail(document_id)['request_reason'] == '合成申請原因已完成'
        layout = browser.evaluate(AUDIT_JS)
        checks[device + 'ApplicationNoOverflowOrErrors'] = not layout['overflow'] and not layout['errors']
        browser.run('screenshot', str(self.output / (device + '-application-committed.png')), '--full')
        evidence['devices'][device] = {'composePaused': paused, 'composeCommitted': committed, 'ordinaryBurst': burst, 'stableControls': stable, 'application': application}
    return self.finish('committed-form-input-desktop-mobile', self.a, checks, evidence)


def verify(output):
    with mock.patch.object(Journey, 'metadata', committed_input_journey):
        return run(output, cases=['metadata'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(0 if verify(args.output)['passed'] else 1)
