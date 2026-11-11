# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from spikes.desktop_ui import CSS
from spikes.sidebar_menu_ui import JS
from tests.test_workspace_navigation import function


class SidebarMenuBrowserTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('M0_DESKTOP_TEST')=='1','Requires Qt/WebEngine')
    def test_clipped_transformed_list_top_layer_fallback_focus_and_cleanup(self):
        harness=r'''
let actions=0;function closeCompactSidebarMenu(){}
const frame=document.querySelector('#frame');
for(let n=0;n<2;n++){
 const row=document.createElement('div');row.className='sidebar-list-row';
 const label=document.createElement('span');label.textContent='Položka '+n;
 row.append(label,sidebarItemMenu('Položka '+n,[{label:'Zobrazit',run:()=>actions++},{label:'Upravit',run:()=>actions++},{label:'Smazat',run:()=>actions++}]));frame.append(row);
}
window.check=(value,message)=>{if(!value)throw Error(message);};
window.pause=()=>new Promise(r=>setTimeout(r,70));
window.runMenuChecks=async()=>{
 const menus=[...frame.querySelectorAll('details')],first=menus[0],second=menus[1];
 for(const fallback of [false,true]){
  if(fallback){frame.style.left='290px';frame.style.top='210px';}
  const items=first.querySelector('[role=menu]');
  if(fallback)Object.defineProperty(items,'showPopover',{value:undefined,configurable:true});
  first.querySelector('summary').click();await pause();
  check(first.open&&activeSidebarMenu?.menu===first,'Menu failed to open');
  const rect=items.getBoundingClientRect(),boundary=frame.getBoundingClientRect();
  check(rect.right>boundary.right||rect.left<boundary.left||rect.top<boundary.top||rect.bottom>boundary.bottom,'Menu stayed constrained to list bounds');
  check(rect.left>=0&&rect.top>=0&&rect.right<=innerWidth&&rect.bottom<=innerHeight,'Menu escaped viewport');
  for(const button of items.querySelectorAll('button')){
   const box=button.getBoundingClientRect();check(button.contains(document.elementFromPoint(box.x+box.width/2,box.y+box.height/2)),'Menu action clipped by scrolling/transform');
  }
  if(!fallback)check(items.matches(':popover-open'),'Expected top-layer popover');
  else check(items.parentNode===document.body,'Fallback did not leave clipping ancestor');
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true}));
  check(document.activeElement.textContent==='Upravit','Menu keyboard navigation failed');
  document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await pause();
  check(!first.open&&!activeSidebarMenu&&document.activeElement===first.querySelector('summary'),'Escape did not restore trigger focus');
  first.querySelector('summary').click();await pause();
  second.querySelector('summary').click();await pause();
  check(!first.open&&second.open&&activeSidebarMenu.menu===second,'Two menus remained open');
  second.querySelector('[role=menuitem]').click();await pause();
  check(!activeSidebarMenu&&actions>0,'Action failed or left overlay open');
  first.querySelector('summary').click();await pause();frame.dispatchEvent(new Event('scroll'));await pause();
  check(!activeSidebarMenu,'Scrolling left stale menu');
  first.querySelector('summary').click();await pause();document.body.click();await pause();
  check(!activeSidebarMenu,'Outside click left stale menu');
  first.querySelector('summary').click();await pause();window.dispatchEvent(new Event('resize'));await pause();
  check(!activeSidebarMenu,'Resize left stale menu');
 }
 // Static menus keep closest(details), including the portal fallback.
 const item=first.querySelector('[role=menu]');Object.defineProperty(item,'showPopover',{value:undefined,configurable:true});
 const staticButton=document.createElement('button');staticButton.setAttribute('role','menuitem');staticButton.textContent='Static';
 staticButton.onclick=()=>{staticButton.closest('details').open=false;actions++;};item.append(staticButton);
 first.querySelector('summary').click();await pause();staticButton.click();await pause();
 check(staticButton.closest('details')===first&&!activeSidebarMenu,'Fallback lost static action owner');
 second.querySelector('summary').click();await pause();frame.replaceChildren();await pause();
 check(!activeSidebarMenu&&!document.querySelector('.sidebar-menu-floating'),'Removed row left orphaned popup');
 return 'menu clipping checks OK';
};
'''
        html='<html><style>'+CSS+'''body{margin:0}#frame{position:absolute;top:90px;left:10px;width:180px;height:75px;overflow:hidden;transform:translateZ(0);background:#183040}.sidebar-list-row{height:36px;color:white}</style><body><div id="frame"></div><script>'''+JS+function('sidebarItemMenu')+harness+'</script></body></html>'
        script=r'''
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEnginePage,QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from shiboken6 import delete
app=QApplication([]);profile=QWebEngineProfile(app);page=QWebEnginePage(profile,app)
view=QWebEngineView();view.setPage(page);view.resize(480,300);view.show()
def loaded(ok):
 page.runJavaScript('runMenuChecks().then(v=>window.menuResult=v).catch(e=>window.menuResult="FAIL: "+e.message)')
def poll():
 page.runJavaScript('window.menuResult||""',result)
def result(value):
 if not value:return
 print(value,flush=True);view.grab().save('/tmp/fpw-sidebar-menu-regression.png');app.exit(0 if value=='menu clipping checks OK' else 2)
page.loadFinished.connect(loaded);page.setHtml(HTML)
timer=QTimer();timer.timeout.connect(poll);timer.start(100)
QTimer.singleShot(15000,lambda:app.exit(3));code=app.exec();view.close();delete(view);delete(page);delete(profile);raise SystemExit(code)
'''.replace('page.setHtml(HTML)','page.setHtml('+repr(html)+')')
        result=subprocess.run([sys.executable,'-c',script],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=25)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('menu clipping checks OK',result.stdout)
