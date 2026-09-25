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
                        + model + script], check=True, text=True)

    def test_private_main_selection_reorders_and_excludes_consumed_slides(self):
        self.run_js("""
const slides=[{title:'A'},{title:'B'},{title:'C'}],seq=createPresenterSequence(slides);
seq.commit(seq.current);
seq.chooseMain(1);
assert.equal(seq.current.slide,slides[0]);assert.equal(seq.next.slide,slides[2]);
seq.commit(seq.next);
assert.deepEqual(seq.entries.map(e=>e.slide.title),['A','C','B']);
assert.equal(seq.next.slide,slides[1]);
assert.equal(seq.available(slides[0]),false);
seq.chooseEntry(seq.entries[0]);assert.equal(seq.next.slide,slides[1]);
seq.commit(seq.next);assert.equal(seq.next,undefined);assert.equal(seq.target(-1),undefined);
assert.equal(createPresenterSequence(slides).available(slides[0]),true);
assert.equal(createPresenterSequence([]).next,undefined);
""")

    def test_backups_return_once_and_repeat_requires_explicit_permission(self):
        self.run_js("""
const slides=[{title:'A'},{title:'B',repeat:true}],seq=createPresenterSequence(slides);
const backup={title:'X'},other={title:'Y'};
seq.commit(seq.current);const origin=seq.current;
seq.chooseBackup(backup);seq.chooseBackup(other);assert.equal(seq.next.slide,other);
seq.choosePlanned();assert.equal(seq.next.slide,slides[1]);
seq.chooseBackup(backup);seq.commit(seq.next);
assert.equal(seq.next,origin);assert.equal(seq.available(backup),false);
assert.equal(seq.chooseBackup(backup),false);
seq.commit(seq.next);assert.equal(seq.current,origin);assert.equal(seq.next.slide,slides[1]);
seq.commit(seq.next);assert.equal(seq.available(slides[1]),true);
seq.chooseBackup(other);seq.commit(seq.next);seq.commit(seq.next);
assert.equal(seq.current.slide,slides[1]);assert.equal(seq.available(other),false);
// Backup chains return to the immediately preceding slide, then its origin.
const chain=createPresenterSequence(slides);chain.commit(chain.current);
chain.chooseBackup(backup);chain.commit(chain.next);
chain.chooseBackup(other);chain.commit(chain.next);
assert.equal(chain.next.slide,backup);chain.commit(chain.next);
assert.equal(chain.next.slide,slides[0]);chain.commit(chain.next);
assert.equal(chain.next.slide,slides[1]);
""")

    def test_progressive_rows_survive_detours_and_complete_without_replay(self):
        self.run_js("""
const slide={id:'one',title:'A',reveal:'step',bullets:['one','two','three']};
const seq=createPresenterSequence([slide,{title:'B'}]),backup={title:'X'};
assert.deepEqual(seq.visual(seq.current,true).bullets,['one']);
seq.commit(seq.current);assert.equal(seq.count(slide),1);
assert.deepEqual(seq.visual(seq.next,true).bullets,['one','two']);
seq.chooseBackup(backup);seq.commit(seq.next);
assert.deepEqual(seq.visual(seq.next,true).bullets,['one','two']);
seq.commit(seq.next);assert.equal(seq.count(slide),2);
seq.chooseMain(1);seq.commit(seq.next); // Leave unfinished A for B.
assert.equal(seq.next.slide,slide);seq.commit(seq.next);
assert.equal(seq.count(slide),3);assert.equal(seq.available(slide),false);
assert.equal(seq.next,undefined);
const empty=createPresenterSequence([{reveal:'step',bullets:[]}]);
empty.commit(empty.current);assert.equal(empty.next,undefined);
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
pad.buttons=[{pressed:true}];assert.deepEqual(read(pad,true),['confirm']);
assert.deepEqual(read(pad,true),[]);
read(pad,false);assert.deepEqual(read(pad,true),[]);
pad.buttons[0].pressed=false;read(pad,true);
pad.buttons[0].pressed=true;assert.deepEqual(read(pad,true),['confirm']);
""")

    def test_gamepad_poll_selects_privately_and_confirms_visible_choice(self):
        poll = JS[JS.index('function pollPresenterGamepad()'):JS.index("addEventListener('gamepadconnected'")]
        self.run_js("""
const pad={index:0,id:'pad',axes:[0,0,0,0],buttons:[{pressed:false}]};
const navigator={getGamepads:()=>[pad]},document={hidden:false,hasFocus:()=>true};
const presenterView={hidden:false},presenterGamepadStatus={};
function requestAnimationFrame(){};function refreshPresenterNext(){};function renderPresenterDeck(){};
let projections=[];
function movePresenter(){projections.push(presenterSequence.next.slide.title);}
function selectPresenterTab(){};function movePresenterItem(){};
let presenterTabIndex=0;
presenterSequence=createPresenterSequence([{title:'A'},{title:'B'},{title:'C'}]);
presenterSequence.commit(presenterSequence.current);
""" + poll + """
pollPresenterGamepad();pad.axes[0]=1;pollPresenterGamepad();
assert.equal(presenterSequence.next.slide.title,'C');assert.deepEqual(projections,[]);
pad.buttons[0].pressed=true;pollPresenterGamepad();assert.deepEqual(projections,['C']);
pollPresenterGamepad();assert.deepEqual(projections,['C']);
presenterView.hidden=true;pad.axes[0]=0;pad.buttons[0].pressed=false;pollPresenterGamepad();
pad.axes[0]=-1;pad.buttons[0].pressed=true;pollPresenterGamepad();
assert.deepEqual(projections,['C']);
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
 fail=false;const home=movePresenter(1);release();await home;
 assert.equal(presenterSequence.current.slide,main[0]);
 const next=movePresenter(1);release();await next;
 assert.equal(presenterSequence.current.slide,main[1]);
 await movePresenter(-1);assert.equal(calls.length,4);
 assert.equal(presenterSequence.current.slide,main[1]);
 assert.equal(presenterSequence.entries.length,3);
})().catch(error=>{console.error(error);process.exitCode=1;});
"""
        self.run_js(harness + navigation + checks)
        self.run_js(harness + navigation + """
(async()=>{
 const slide={id:'one',deck_revision:'rev',reveal:'step',bullets:['one','two'],title:'A'};
 presenterSequence=createPresenterSequence([slide]);
 const first=showPresenterEntry(presenterSequence.current);
 assert.equal(calls[0].rows,1);assert.equal(presenterSequence.count(slide),0);
 release();await first;assert.equal(presenterSequence.count(slide),1);
 fail=true;await movePresenter(1);assert.equal(presenterSequence.count(slide),1);
 fail=false;const second=movePresenter(1);
 assert.equal(calls[2].rows,2);release();await second;
 assert.equal(presenterSequence.count(slide),2);assert.equal(presenterSequence.next,undefined);
})().catch(error=>{console.error(error);process.exitCode=1;});
""")
