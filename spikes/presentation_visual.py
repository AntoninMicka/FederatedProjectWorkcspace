# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""The same safe slide renderer is shipped in speaker and audience assets."""
SLIDE_JS = r'''
function renderSlideVisual(target,slide,heading='h2'){
 target.replaceChildren();
 const color=(value,fallback)=>/^#[0-9a-fA-F]{6}$/.test(value || '')?value:fallback;
 target.style.backgroundColor=color(slide?.background,'#102b36');
 target.style.color=color(slide?.foreground,'#ffffff');
 const wallpaper=slide?.wallpaper || '';
 target.style.backgroundImage=/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(wallpaper)?`url("${wallpaper}")`:'none';
 target.style.backgroundSize='cover';target.style.backgroundPosition='center';
 target.style.boxSizing='border-box';target.style.padding='5%';
 if(!slide){target.textContent='Žádný slide k zobrazení.';return;}
 const title=document.createElement(heading);title.textContent=slide.title;title.style.color='inherit';
 target.append(title);
 if(Array.isArray(slide.bullets)){
  const list=document.createElement('ul');
  for(const text of slide.bullets){const item=document.createElement('li');item.textContent=text;list.append(item);}
  target.append(list);
 }else{
  const body=document.createElement('p');body.textContent=slide.body || '';target.append(body);
 }
}
'''
