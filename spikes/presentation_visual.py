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
 target.style.position='relative';target.style.containerType='inline-size';
 target.style.minHeight=slide?.closing?'180px':'';
 if(!slide){target.textContent='Žádný slide k zobrazení.';return;}
 const title=document.createElement(heading);title.textContent=slide.title;title.style.color='inherit';
 target.append(title);
 if(slide.closing===true){
  if(!target.style.aspectRatio)target.style.aspectRatio='16 / 9';
  Object.assign(title.style,{position:'absolute',top:'50%',left:'5%',width:'90%',transform:'translateY(-50%)',textAlign:'center',margin:'0',fontSize:'clamp(12px,4cqw,72px)'});
  const footer=document.createElement('div');
  Object.assign(footer.style,{position:'absolute',bottom:'5%',right:'5%',width:'90%',display:'flex',alignItems:'flex-end',justifyContent:'flex-end',gap:'3%'});
  const contacts=document.createElement('div');
  Object.assign(contacts.style,{whiteSpace:'pre-wrap',textAlign:'right',overflowWrap:'anywhere',maxWidth:'70%',fontSize:'clamp(8px,1.7cqw,28px)',lineHeight:'1.3'});
  contacts.textContent=(slide.contacts || []).join('\n');footer.append(contacts);
  if(/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(slide.qr || '')){
   const qr=document.createElement('img');qr.src=slide.qr;qr.alt='Kontakty řečníka v QR kódu';
   Object.assign(qr.style,{width:'22%',height:'auto',flexShrink:'0',imageRendering:'pixelated'});footer.append(qr);
  }
  target.append(footer);return;
 }
 if(Array.isArray(slide.bullets)){
  const list=document.createElement('ul');
  for(const text of slide.bullets){const item=document.createElement('li');item.textContent=text;list.append(item);}
  target.append(list);
 }else{
  const body=document.createElement('p');body.textContent=slide.body || '';target.append(body);
 }
}
'''
