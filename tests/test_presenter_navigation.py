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
seq.commit(seq.next);assert.equal(seq.next,undefined);assert.equal(seq.target(-1).slide,slides[2]);
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
seq.commit(seq.next);assert.equal(seq.current.slide,origin.slide);assert.equal(seq.next.slide,slides[1]);
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

    def test_backward_history_preserves_order_and_closing_stays_last(self):
        self.run_js("""
const a={title:'A'},b={title:'B'},c={title:'C'},end={title:'Questions',closing:true};
const seq=createPresenterSequence([a,b,c,end]);
assert.equal(seq.canShow(seq.entries[3]),false);
seq.commit(seq.current);seq.chooseMain(1);seq.commit(seq.next);
const backup={title:'Backup'};seq.chooseBackup(backup);seq.commit(seq.next);seq.commit(seq.next);
assert.deepEqual(seq.entries.map(e=>e.slide.title),['A','C','Backup','C','B','Questions']);
const route=seq.entries.slice();
seq.commit(seq.target(-1),true);assert.equal(seq.current.slide,backup);
seq.commit(seq.target(-1),true);assert.equal(seq.current.slide,c);
seq.commit(seq.target(-1),true);assert.equal(seq.current.slide,a);
assert.equal(seq.target(-1),undefined);assert.deepEqual(seq.entries,route);
assert.equal(seq.available(a),false);assert.equal(seq.available(backup),false);
assert.equal(seq.next.slide,b);seq.commit(seq.next);
assert.deepEqual(seq.entries.map(e=>e.slide.title),['A','C','Backup','C','B','Questions']);
assert.equal(seq.next.slide,end);seq.commit(seq.next);assert.equal(seq.next,undefined);
seq.commit(seq.target(-1),true);assert.equal(seq.current.slide,b);
assert.equal(seq.entries.at(-1).slide,end);
// Empty deck and partial step slide: history traversal never resets rows.
assert.deepEqual(createPresenterSequence([]).choices,[]);
const step={title:'Step',reveal:'step',bullets:['1','2','3']};
const rows=createPresenterSequence([step,b,end]);rows.commit(rows.current);
rows.chooseMain(1);rows.commit(rows.next);rows.commit(rows.target(-1),true);
assert.equal(rows.count(step),2);assert.equal(rows.next.slide,step);
rows.commit(rows.next);assert.equal(rows.next.slide,end);
""")

    def test_full_route_is_visible_but_consumed_slides_are_not_choices(self):
        renderer = JS[JS.index('function renderPresenterDeck()'):JS.index('function choosePresenterBackup(')]
        self.run_js("""
const element=()=>({children:[],classList:{toggle(){}},setAttribute(){},addEventListener(){},append(item){this.children.push(item);},replaceChildren(){this.children=[];}});
const presenterDeckList=element(),document={createElement:element};
function refreshPresenterNext(){};
presenterSequence=createPresenterSequence([{title:'A'},{title:'B'},{title:'C'}]);
presenterSequence.commit(presenterSequence.current);presenterSequence.commit(presenterSequence.next);
""" + renderer + """
renderPresenterDeck();assert.equal(presenterDeckList.children.length,3);
assert.equal(presenterDeckList.children[0].children[0].disabled,true);
assert.equal(presenterDeckList.children[2].children[0].disabled,false);
presenterSequence.commit(presenterSequence.target(-1),true);renderPresenterDeck();
assert.equal(presenterDeckList.children.length,3);
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
pad.axes=[0,1,1,0];assert.deepEqual(read(pad,true),['mainNext','tabNext']);
assert.deepEqual(read(pad,true),[]);
pad.axes[1]=-1;assert.deepEqual(read(pad,true),[]);
pad.axes[1]=0;read(pad,true);pad.axes[1]=-1;
assert.deepEqual(read(pad,true),['mainPrevious']);
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
function movePresenter(delta){projections.push(delta<0?'previous':presenterSequence.next.slide.title);}
function selectPresenterTab(){};function movePresenterItem(){};
let presenterTabIndex=0;
presenterSequence=createPresenterSequence([{title:'A'},{title:'B'},{title:'C'}]);
presenterSequence.commit(presenterSequence.current);
""" + poll + """
pollPresenterGamepad();pad.axes[1]=1;pollPresenterGamepad();
assert.equal(presenterSequence.next.slide.title,'C');assert.deepEqual(projections,[]);
pad.axes[1]=0;pollPresenterGamepad();pad.axes[1]=-1;pollPresenterGamepad();
assert.equal(presenterSequence.next.slide.title,'B');assert.deepEqual(projections,[]);
pad.axes[1]=0;pollPresenterGamepad();pad.axes[1]=1;pollPresenterGamepad();
pad.axes[0]=1;pollPresenterGamepad();assert.deepEqual(projections,['C']);
pollPresenterGamepad();assert.deepEqual(projections,['C']);
pad.axes[0]=0;pollPresenterGamepad();pad.axes[0]=-1;pollPresenterGamepad();
assert.deepEqual(projections,['C','previous']);
pad.axes[0]=0;pad.axes[1]=0;pollPresenterGamepad();
// A diagonal must project the existing choice, not the newly selected one.
pad.axes=[1,-1,0,0];pollPresenterGamepad();
assert.equal(presenterSequence.next.slide.title,'C');
assert.deepEqual(projections,['C','previous','C']);
pad.axes=[0,0,0,0];pollPresenterGamepad();
pad.buttons[0].pressed=true;pollPresenterGamepad();
assert.deepEqual(projections,['C','previous','C','C']);
presenterView.hidden=true;pad.axes[0]=0;pad.buttons[0].pressed=false;pollPresenterGamepad();
pad.axes[0]=-1;pad.buttons[0].pressed=true;pollPresenterGamepad();
assert.deepEqual(projections,['C','previous','C','C']);
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
 presenterSequence=createPresenterSequence(main);presenterSequence.commit(presenterSequence.current);presenterSequence.chooseBackup(backup);
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
 const route=presenterSequence.entries.slice();
 fail=true;await movePresenter(-1);assert.equal(presenterSequence.current.slide,main[1]);
 fail=false;const back=movePresenter(-1);release();await back;
 assert.equal(calls.length,6);assert.equal(presenterSequence.current.slide,main[0]);
 assert.deepEqual(presenterSequence.entries,route);
 assert.equal(presenterSequence.entries.length,4);
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
