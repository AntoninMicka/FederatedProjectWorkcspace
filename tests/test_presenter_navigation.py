# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Behavior of the presenter's temporary sequence and gamepad gestures."""
import shutil
import subprocess
import unittest

from spikes.desktop_ui import JS


@unittest.skipUnless(shutil.which('node'), 'Requires Node.js')
class PresenterNavigationTests(unittest.TestCase):
    def run_js(self, script):
        model = JS[JS.index('function createPresenterSequence('):
                   JS.index('function renderPresenterContent(')]
        subprocess.run(['node', '-e', "const assert=require('node:assert/strict');\n"
                        + model + script], check=True, capture_output=True, text=True)

    def test_sequence_preserves_backup_order_and_can_replace_unshown_choice(self):
        self.run_js("""
const slides=[{title:'A'},{title:'B'},{title:'C'}];
const first={title:'Backup 1'},second={title:'Backup 2'};
const seq=createPresenterSequence(slides);
seq.chooseBackup(first);
assert.equal(seq.current.slide,slides[0]);
assert.equal(seq.next.slide,first);
seq.chooseBackup(second);
assert.deepEqual(seq.entries.map(e=>e.slide.title),['A','Backup 2','B','C']);
seq.choosePlanned();
assert.deepEqual(seq.entries.map(e=>e.slide.title),['A','B','C']);
seq.chooseBackup(first);seq.commit(seq.target(1));
assert.equal(seq.current.mainIndex,0);
seq.chooseBackup(second);seq.commit(seq.target(1));
seq.commit(seq.target(1));
assert.equal(seq.current.slide,slides[1]);
const backwards=[];
while(seq.target(-1)){seq.commit(seq.target(-1));backwards.push(seq.current.slide.title);}
assert.deepEqual(backwards,['Backup 2','Backup 1','A']);
seq.chooseBackup(first); // Reuse the already recorded next occurrence.
assert.equal(seq.entries.length,5);
const forwards=[];
while(seq.target(1)){seq.commit(seq.target(1));forwards.push(seq.current.slide.title);}
assert.deepEqual(forwards,['Backup 1','Backup 2','B','C']);
assert.equal(seq.target(1),undefined);
seq.chooseBackup(first);seq.commit(seq.target(1)); // Also works after the last main slide.
assert.equal(seq.current.mainIndex,2);
assert.equal(seq.planned,undefined);
seq.commit(seq.target(-1));assert.equal(seq.current.slide,slides[2]);
assert.deepEqual(slides.map(s=>s.title),['A','B','C']);
assert.equal(createPresenterSequence(slides).entries.length,3); // A new session resets the route.
const empty=createPresenterSequence([]);empty.chooseBackup(first);empty.choosePlanned();
assert.equal(empty.entries.length,0);assert.equal(empty.next,undefined);
const revisit=createPresenterSequence(slides);
revisit.chooseBackup(first);revisit.commit(revisit.next);revisit.commit(revisit.next);
revisit.commit(revisit.target(-1));revisit.commit(revisit.target(-1));
revisit.choosePlanned();revisit.commit(revisit.next);
assert.equal(revisit.current.slide,slides[1]);
revisit.commit(revisit.target(-1));assert.equal(revisit.current.slide,first);
""")

    def test_joysticks_are_independent_and_require_neutral_after_activation(self):
        self.run_js("""
const read=createPresenterGamepadInput();
const pad={index:0,id:'Controller',axes:[1,0,0,0]};
assert.deepEqual(read(pad,true),[]); // Connecting while tilted must not advance.
pad.axes[0]=0;assert.deepEqual(read(pad,true),[]);
pad.axes[0]=1;assert.deepEqual(read(pad,true),['next']);
assert.deepEqual(read(pad,true),[]); // Held stick, no repeat.
pad.axes[0]=-1;assert.deepEqual(read(pad,true),[]); // Must cross sampled neutral first.
pad.axes[0]=0;read(pad,true);pad.axes[0]=-1;
assert.deepEqual(read(pad,true),['previous']);
pad.axes=[0,1,1,0];assert.deepEqual(read(pad,true),['tabNext']);
pad.axes=[0,0,0,1];assert.deepEqual(read(pad,true),['itemNext']);
read(pad,false);pad.axes=[1,0,0,0];assert.deepEqual(read(pad,true),[]);
pad.axes[0]=0;read(pad,true);pad.axes[0]=1;assert.deepEqual(read(pad,true),['next']);
read(null,true);assert.deepEqual(read(pad,true),[]); // Reconnect needs neutral.
pad.id='Replacement';assert.deepEqual(read(pad,true),[]);
pad.axes=[0,0];read(pad,true);pad.axes[0]=-1;
assert.deepEqual(read(pad,true),['previous']); // No fallback from left to right stick.
""")

    def test_navigation_commits_only_on_success_and_serializes_requests(self):
        navigation = JS[JS.index('async function showPresenterEntry('):
                        JS.index('function renderPrivateSelection(')]
        harness = """
const element=()=>({disabled:false,textContent:'',classList:{remove(){}}});
const presenterPrevButton=element(),presenterNextButton=element(),presenterNextPreview=element();
const presenterView=element(),presenterBlackoutButton=element(),presenterBlackoutState=element();
const presenterLiveState=element(),presenterExposure=element(),presenterPrivateStatus=element(),presenterStatus=element();
let presenterBlackout=false,presenterExposureValue=0,presenterPrivateSelection=null,presenterIndex=0;
let renders=0;
function renderPresenterSlide(){renders++;presenterIndex=presenterSequence.current.mainIndex;}
let release,fail=false,calls=[];
async function presentationControl(payload){calls.push(payload);if(fail)throw new Error('offline');await new Promise(resolve=>release=resolve);}
"""
        checks = """
(async()=>{
 const main=[{title:'A',body:'main',notes:'private'},{title:'B',body:'next'}];
 const backup={title:'Backup',body:'public',notes:'secret'};
 presenterSequence=createPresenterSequence(main);presenterSequence.chooseBackup(backup);
 const first=movePresenter(1);await movePresenter(1);
 assert.equal(calls.length,1);assert.equal(presenterSequence.current.slide,main[0]);
 assert.deepEqual(calls[0].content,{title:'Backup',body:'public'});
 release();await first;assert.equal(presenterSequence.current.slide,backup);
 assert.equal(presenterExposureValue,1);assert.equal(presenterNavigating,false);
 fail=true;await movePresenter(1);
 assert.equal(presenterSequence.current.slide,backup);assert.equal(presenterNavigating,false);
 assert.equal(presenterStatus.textContent,'offline');
 assert.match(presenterPrivateStatus.textContent,/nebylo potvrzeno/);
 fail=false;const next=movePresenter(1);release();await next;
 assert.equal(presenterSequence.current.slide,main[1]);
 const back=movePresenter(-1);release();await back;
 assert.equal(presenterSequence.current.slide,backup);
 const home=returnPresenterMain();release();await home;
 assert.equal(presenterSequence.current.slide,main[0]);
 assert.equal(presenterSequence.entries.length,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        self.run_js(harness + navigation + checks)
