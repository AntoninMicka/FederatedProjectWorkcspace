# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Shared item menus escape scroll containers without changing action owners."""
CSS='''
.sidebar-item-menu-items.sidebar-menu-floating{position:fixed;inset:auto;margin:0;box-sizing:border-box;width:205px;max-width:calc(100vw - 16px);max-height:calc(100dvh - 16px);overflow:auto;z-index:10000}
'''
JS=r'''
let activeSidebarMenu=null;
function closeSidebarItemMenu(restoreFocus=false){
 const state=activeSidebarMenu;if(!state)return;activeSidebarMenu=null;
 state.observer.disconnect();
 if(state.topLayer&&state.items.matches(':popover-open'))state.items.hidePopover();
 if(state.placeholder)state.placeholder.replaceWith(state.items);
 state.items.classList.remove('sidebar-menu-floating');state.items.style.cssText=state.originalStyle;
 state.menu.open=false;state.trigger.setAttribute('aria-expanded','false');
 if(restoreFocus&&state.trigger.isConnected)state.trigger.focus({preventScroll:true});
}
function placeSidebarItemMenu(state){
 const {items,trigger}=state,anchor=trigger.getBoundingClientRect();
 const width=document.documentElement.clientWidth,height=window.innerHeight;
 items.style.maxWidth=Math.max(0,width-16)+'px';items.style.maxHeight=Math.max(0,height-16)+'px';
 const rect=items.getBoundingClientRect();
 const x=anchor.right+6+rect.width<=width-8?anchor.right+6:Math.max(8,Math.min(anchor.left-rect.width-6,width-rect.width-8));
 let y=anchor.bottom+4;
 if(y+rect.height>height-8)y=anchor.top-rect.height-4;
 items.style.left=x+'px';items.style.top=Math.max(8,Math.min(y,height-rect.height-8))+'px';
}
function openSidebarItemMenu(menu){
 if(activeSidebarMenu?.menu===menu)return;
 closeSidebarItemMenu();
 const trigger=menu.querySelector(':scope > summary'),items=menu.querySelector(':scope > .sidebar-item-menu-items');
 if(!trigger||!items)return;
 for(const other of document.querySelectorAll('details.sidebar-item-menu[open]'))if(other!==menu)other.open=false;
 const state={menu,trigger,items,originalStyle:items.style.cssText,topLayer:typeof items.showPopover==='function',placeholder:null};
 state.observer=new MutationObserver(()=>{if(!menu.isConnected)closeSidebarItemMenu();});
 activeSidebarMenu=state;trigger.setAttribute('aria-expanded','true');
 items.classList.add('sidebar-menu-floating');
 if(state.topLayer){
  items.setAttribute('popover','auto');items.showPopover();
  if(!items.dataset.sidebarPopoverBound){
   items.dataset.sidebarPopoverBound='true';
   items.addEventListener('toggle',event=>{if(event.newState==='closed'&&activeSidebarMenu?.items===items)closeSidebarItemMenu();});
  }
 }else{
  // Keep the original controls/listeners. Restore their parent before dispatch
  // so existing closest('details') and delegated actions continue to work.
  items.removeAttribute('popover');
  state.placeholder=document.createComment('sidebar menu');items.before(state.placeholder);document.body.append(items);items.style.display='block';
 }
 placeSidebarItemMenu(state);
 state.observer.observe(document.body,{childList:true,subtree:true});
 items.querySelector('[role="menuitem"]:not(:disabled)')?.focus({preventScroll:true});
}
document.addEventListener('toggle',event=>{
 const menu=event.target;if(!(menu instanceof Element)||!menu.matches('details.sidebar-item-menu'))return;
 if(menu.open)openSidebarItemMenu(menu);else if(activeSidebarMenu?.menu===menu)closeSidebarItemMenu();
},true);
document.addEventListener('click',event=>{
 const state=activeSidebarMenu;if(!state)return;
 const inside=state.items.contains(event.target);
 if((inside&&event.target.closest('[role="menuitem"]'))||(!inside&&!state.menu.contains(event.target)))closeSidebarItemMenu();
},true);
document.addEventListener('keydown',event=>{
 const state=activeSidebarMenu;if(!state)return;
 if(event.key==='Escape'){event.preventDefault();event.stopPropagation();closeSidebarItemMenu(true);return;}
 if(event.key==='Tab'){closeSidebarItemMenu(true);return;}
 if(!state.items.contains(event.target)||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
 const buttons=[...state.items.querySelectorAll('[role="menuitem"]:not(:disabled)')];if(!buttons.length)return;
 event.preventDefault();const index=buttons.indexOf(document.activeElement);
 const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
 buttons[next].focus();
},true);
window.addEventListener('resize',()=>closeSidebarItemMenu());
document.addEventListener('scroll',event=>{
 if(activeSidebarMenu&&!activeSidebarMenu.items.contains(event.target))closeSidebarItemMenu();
},true);
'''
