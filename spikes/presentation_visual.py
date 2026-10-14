# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""The same safe slide renderer is shipped in speaker and audience assets."""
SLIDE_JS = r'''
function renderSlideVisual(target,slide,heading='h2'){
 target.replaceChildren();
 const color=(value,fallback)=>/^#[0-9a-fA-F]{6}$/.test(value || '')?value:fallback;
 const layout=slide?.layout && typeof slide.layout==='object'?slide.layout:{};
 const preset=['title','title-content','two-column','visual','closing'].includes(layout.preset)?layout.preset:'title-content';
 const align=value=>['left','center','right'].includes(value)?value:'left';
 const density=['compact','normal','spacious'].includes(layout.density)?layout.density:'normal';
 target.style.backgroundColor=color(slide?.background,color(layout.background,'#102b36'));
 target.style.color=color(slide?.foreground,color(layout.foreground,'#ffffff'));
 const wallpaper=slide?.wallpaper || '';
 const validWallpaper=/^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(wallpaper);
 target.style.backgroundImage=validWallpaper&&preset!=='visual'?`url("${wallpaper}")`:'none';
 target.style.backgroundSize='cover';target.style.backgroundPosition='center';
 target.style.boxSizing='border-box';target.style.padding='0';target.style.overflow='hidden';
 target.style.position='relative';target.style.containerType='inline-size';
 target.style.minHeight=slide?.closing?'180px':'';
 if(!slide){target.textContent='Žádný slide k zobrazení.';return;}
 const title=document.createElement(heading);title.textContent=slide.title;title.style.color='inherit';
 if(slide.closing===true){
  target.append(title);
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
 const titleZone=document.createElement('div'),contentZone=document.createElement('div');
 titleZone.className='slide-layout-title';contentZone.className='slide-layout-content';titleZone.append(title);target.append(titleZone,contentZone);
 const sizes={compact:['clamp(13px,3.3cqw,58px)','clamp(9px,1.65cqw,28px)'],normal:['clamp(14px,3.8cqw,64px)','clamp(10px,1.9cqw,32px)'],spacious:['clamp(16px,4.4cqw,72px)','clamp(11px,2.2cqw,36px)']}[density];
 Object.assign(titleZone.style,{position:'absolute',left:'6%',width:'88%',textAlign:align(layout.title_align),overflow:'hidden'});
 Object.assign(title.style,{margin:'0',fontSize:sizes[0],lineHeight:'1.08',color:color(layout.accent,target.style.color)});
 Object.assign(contentZone.style,{position:'absolute',left:'7%',width:'86%',textAlign:align(layout.content_align),overflow:'hidden',fontSize:sizes[1],lineHeight:density==='compact'?'1.25':'1.4'});
 const justify={left:'flex-start',center:'center',right:'flex-end'}[align(layout.title_align)];
 if(preset==='title'){Object.assign(titleZone.style,{top:'24%',height:'32%',display:'flex',alignItems:'center',justifyContent:justify});Object.assign(contentZone.style,{top:'62%',height:'24%'});}
 else if(preset==='visual'){Object.assign(titleZone.style,{top:'6%',height:'14%'});Object.assign(contentZone.style,{top:'82%',height:'12%'});if(validWallpaper){const visual=document.createElement('img');visual.src=wallpaper;visual.alt=slide.title;Object.assign(visual.style,{position:'absolute',left:'8%',top:'23%',width:'84%',height:'54%',objectFit:'contain'});target.append(visual);}}
 else if(preset==='closing'){Object.assign(titleZone.style,{top:'28%',height:'28%',display:'flex',alignItems:'center',justifyContent:justify});Object.assign(contentZone.style,{top:'68%',height:'20%'});}
 else{Object.assign(titleZone.style,{top:'8%',height:'18%'});Object.assign(contentZone.style,{top:'30%',height:'60%'});}
 const bullets=Array.isArray(slide.bullets)?slide.bullets:null;
 const makeList=items=>{const list=document.createElement('ul');Object.assign(list.style,{margin:'0',paddingLeft:align(layout.content_align)==='left'?'1.25em':'0',listStylePosition:align(layout.content_align)==='left'?'outside':'inside'});for(const text of items){const item=document.createElement('li');item.textContent=text;item.style.marginBottom=density==='compact'?'.18em':'.4em';list.append(item);}return list;};
 if(preset==='two-column'&&bullets){const split=Number.isInteger(slide.column_break)&&slide.column_break>0?slide.column_break:Math.ceil(bullets.length/2),columns=document.createElement('div');Object.assign(columns.style,{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'8%',height:'100%'});columns.append(makeList(bullets.slice(0,split)),makeList(bullets.slice(split)));contentZone.append(columns);}
 else if(bullets)contentZone.append(makeList(bullets));
 else{const body=document.createElement('p');body.textContent=slide.body || '';body.style.margin='0';contentZone.append(body);}
}
'''
