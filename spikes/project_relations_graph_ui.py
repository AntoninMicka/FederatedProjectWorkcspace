# SPDX-FileCopyrightText: 2026 Antonín Mička
# SPDX-License-Identifier: MPL-2.0
"""Read-only relationship graph using the shared page shell and SVG helpers."""
HTML = '''<div id="project-relations-graph-page" hidden data-chat-default="hidden">
<h1>Graf vztahů projektů</h1>
<div class="relation-graph-controls"><label>Zobrazit <select id="relation-graph-scope"><option value="current">Aktuální projekt</option><option value="all">Všechny dostupné projekty</option></select></label>
<button id="relation-graph-refresh" type="button">Obnovit</button>
<button id="relation-graph-out" type="button" aria-label="Oddálit graf vztahů">−</button><button id="relation-graph-reset" type="button">100 %</button><button id="relation-graph-in" type="button" aria-label="Přiblížit graf vztahů">+</button></div>
<p id="relation-graph-status" role="status"></p>
<p class="relations-note">Šipka rodič → podprojekt označuje hierarchii; data jsou dostupná opačně. Šipka závislý → poskytovatel označuje využití výstupů. Souvislost platí obousměrně. Plná čára: aktivní · přerušovaná: čeká · tečkovaná: ukončená nebo nedostupná.</p>
<div class="relation-graph-layout"><div id="relation-graph-canvas" tabindex="0" aria-label="Graf projektů, posuvná oblast"></div><section id="relation-graph-detail" aria-label="Detail výběru"><p>Vyberte projekt nebo vztah v grafu.</p></section></div>
</div>'''
CSS = '''
#sidebar-project-graph{margin:8px 0;width:100%}
.relation-graph-controls{display:flex;flex-wrap:wrap;align-items:center;gap:8px}.relation-graph-controls label{display:flex;gap:8px;align-items:center}
.relation-graph-layout{display:grid;grid-template-columns:minmax(0,1fr) 260px;gap:16px;flex:1;min-height:320px}
#relation-graph-canvas{overflow:auto;min-height:320px;border:1px solid #c9d8df;background:#f6f9fa;border-radius:10px}
#relation-graph-canvas svg{display:block}.relation-graph-node{cursor:pointer}.relation-graph-node rect{fill:white;stroke:#668795;stroke-width:2}
.relation-graph-node[data-current=true] rect{fill:#e0f2ec;stroke:#187469;stroke-width:3}.relation-graph-node:focus rect,.relation-graph-node:hover rect{stroke:#073b67;stroke-width:4}
.relation-graph-edge{cursor:pointer}.relation-graph-edge:focus .relation-edge-line,.relation-graph-edge:hover .relation-edge-line{stroke-width:4}
#relation-graph-detail{overflow-wrap:anywhere}#relation-graph-detail button{display:block;margin:10px 0}
@media(max-width:1400px){.relation-graph-layout{grid-template-columns:minmax(0,1fr)}#relation-graph-detail{min-height:100px}}
'''
JS = r'''
let relationGraphData=null,relationGraphEpoch=0,relationGraphZoom=1;
const relationGraphPage=document.querySelector('#project-relations-graph-page');
function graphActivate(node,action){node.setAttribute('tabindex','0');node.setAttribute('role','button');node.addEventListener('click',action);node.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();action();}});}
async function openRelationGraph(){
 if(!await canLeaveWorkspaceEditors())return;
 selectSidebarTab(document.querySelector('#projects-tab'));showWorkspacePage(relationGraphPage);
 const scope=document.querySelector('#relation-graph-scope');scope.querySelector('[value=current]').disabled=!activeProject;
 scope.value=activeProject?'current':'all';await refreshRelationGraph();
}
async function refreshRelationGraph(){
 const epoch=++relationGraphEpoch,scope=document.querySelector('#relation-graph-scope').value,root=scope==='current'?activeProject?.id:null;
 const status=document.querySelector('#relation-graph-status');relationGraphData=null;
 document.querySelector('#relation-graph-canvas').replaceChildren();document.querySelector('#relation-graph-detail').replaceChildren(relNode('p','Vyberte projekt nebo vztah v grafu.'));
 if(scope==='current'&&!root){status.textContent='Nejprve otevřete projekt nebo zvolte všechny dostupné projekty.';return;}
 status.textContent='Načítám dostupné vztahy…';
 try{const value=await projectRequest('/v1/project-relations/graph',{project_id:root},120000);
  if(epoch!==relationGraphEpoch)return;
  relationGraphData=value;renderRelationGraph();
  const name=value.nodes.find(n=>n.id===root)?.title;
  status.textContent=`${root?'Propojené projekty: '+name:'Všechny dostupné projekty'} · ${value.nodes.length} projektů · ${value.edges.length} vztahů`;
 }catch(error){if(epoch===relationGraphEpoch)status.textContent='Graf nelze načíst: '+error.message;}
}
function renderRelationGraph(){
 const data=relationGraphData,box=document.querySelector('#relation-graph-canvas');box.replaceChildren();if(!data)return;
 if(!data.nodes.length){box.append(relNode('p','Nemáte dostupné žádné projekty.'));return;}
 const nodes=[...data.nodes].sort((a,b)=>a.title.localeCompare(b.title)),adj=new Map(nodes.map(n=>[n.id,[]])),rank=new Map();
 for(const e of data.edges){adj.get(e.source).push(e.target);adj.get(e.target).push(e.source);}
 const starts=[...nodes].sort((a,b)=>Number(b.current)-Number(a.current)||Number(data.edges.some(e=>e.target===a.id&&e.type!=='relates_to'))-Number(data.edges.some(e=>e.target===b.id&&e.type!=='relates_to')));
 for(const start of starts){if(rank.has(start.id))continue;rank.set(start.id,0);const queue=[start.id];for(let i=0;i<queue.length;i++)for(const next of adj.get(queue[i]))if(!rank.has(next)){rank.set(next,rank.get(queue[i])+1);queue.push(next);}}
 const columns=new Map(),positions=new Map();
 for(const n of nodes){const depth=rank.get(n.id),column=columns.get(depth)||[];positions.set(n.id,{x:30+depth*330,y:40+column.length*130});column.push(n);columns.set(depth,column);}
 const width=Math.max(780,(Math.max(...rank.values())+1)*330),height=Math.max(380,Math.max(...[...columns.values()].map(v=>v.length))*130+60);
 const svg=roadmapElement('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'group','aria-label':'Vztahy projektů'}),defs=roadmapElement('defs');
 for(const [id,color] of [['hierarchy','#187469'],['dependency','#5361a3'],['related','#98713c']]){const marker=roadmapElement('marker',{id:'project-edge-'+id,viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:7,markerHeight:7,orient:'auto-start-reverse'});marker.append(roadmapElement('path',{d:'M0 0 L10 5 L0 10z',fill:color}));defs.append(marker);}svg.append(defs);
 for(const e of data.edges){const a=positions.get(e.source),b=positions.get(e.target),forward=b.x>=a.x,x1=forward?a.x+230:a.x,y1=a.y+34,x2=forward?b.x:b.x+230,y2=b.y+34;
  const style=e.type==='parent_of'?'hierarchy':e.type==='depends_on'?'dependency':'related',color={hierarchy:'#187469',dependency:'#5361a3',related:'#98713c'}[style];
  const d=a.x===b.x?`M ${a.x+230} ${y1} C ${a.x+290} ${y1}, ${b.x+290} ${y2}, ${b.x+230} ${y2}`:`M ${x1} ${y1} C ${(x1+x2)/2} ${y1}, ${(x1+x2)/2} ${y2}, ${x2} ${y2}`;
  const group=roadmapElement('g',{'class':'relation-graph-edge','data-relation-id':e.id,'aria-label':RELATION_TYPES[e.type]+' · '+(RELATION_STATES[e.state]||e.state)}),title=roadmapElement('title');title.textContent=RELATION_TYPES[e.type]+' · '+(RELATION_STATES[e.state]||e.state);group.append(title);
  group.append(roadmapElement('path',{d,fill:'none',stroke:'transparent','stroke-width':18}));
  group.append(roadmapElement('path',{d,fill:'none',stroke:color,'stroke-width':2,'class':'relation-edge-line','stroke-dasharray':e.state==='active'?'none':e.state==='pending'?'9 5':'2 5','marker-end':'url(#project-edge-'+style+')',...(e.type==='relates_to'?{'marker-start':'url(#project-edge-'+style+')'}:{})}));
  const label=roadmapElement('text',{x:a.x===b.x?a.x+278:(x1+x2)/2,y:(y1+y2)/2-10,'text-anchor':'middle','font-size':11,fill:color,stroke:'#f6f9fa','stroke-width':4,'paint-order':'stroke'});label.textContent={parent_of:'Podprojekt',depends_on:'Závisí na',relates_to:'Souvisí'}[e.type];group.append(label);
  graphActivate(group,()=>showRelationGraphDetail('edge',e));svg.append(group);
 }
 for(const n of nodes){const p=positions.get(n.id),g=roadmapElement('g',{'class':'relation-graph-node','data-project-id':n.id,'data-current':n.current,'aria-label':n.title});
  const title=roadmapElement('title');title.textContent=n.title;g.append(title,roadmapElement('rect',{x:p.x,y:p.y,width:230,height:68,rx:10}));
  const text=roadmapElement('text',{x:p.x+14,y:p.y+29,fill:'#213746','font-size':14});text.textContent=n.title.length>27?n.title.slice(0,25)+'…':n.title;
  const subtitle=roadmapElement('text',{x:p.x+14,y:p.y+49,fill:'#526675','font-size':11});subtitle.textContent=n.current?'Aktuální projekt':n.navigable?'Projekt':'Dostupný přes vztah';g.append(text,subtitle);graphActivate(g,()=>showRelationGraphDetail('node',n));svg.append(g);
 }
 box.append(svg);applyRelationGraphZoom();
}
function applyRelationGraphZoom(){const svg=document.querySelector('#relation-graph-canvas svg');if(svg){svg.style.width=(svg.viewBox.baseVal.width*relationGraphZoom)+'px';svg.style.height=(svg.viewBox.baseVal.height*relationGraphZoom)+'px';}
 document.querySelector('#relation-graph-reset').textContent=Math.round(relationGraphZoom*100)+' %';document.querySelector('#relation-graph-out').disabled=relationGraphZoom<=.5;document.querySelector('#relation-graph-in').disabled=relationGraphZoom>=2;}
function showRelationGraphDetail(kind,value){
 const box=document.querySelector('#relation-graph-detail');box.replaceChildren();
 if(kind==='node'){box.append(relNode('h2',value.title));if(value.navigable)box.append(relButton('Otevřít projekt',()=>openRegisteredProject(value.id)));else box.append(relNode('p','Projekt je dostupný prostřednictvím schváleného vztahu; přímé otevření vyžaduje vlastní oprávnění.'));if(value.navigable)box.append(relButton('Vztahy a podklady',async()=>{if(!await canLeaveWorkspaceEditors())return;await openRegisteredProject(value.id);await openProjectRelations();}));}
 else{const name=id=>relationGraphData.nodes.find(n=>n.id===id)?.title||'';box.append(relNode('h2',RELATION_TYPES[value.type]),relNode('p',name(value.source)+(value.type==='relates_to'?' ↔ ':' → ')+name(value.target)),relNode('p',RELATION_STATES[value.state]||value.state),relNode('p',value.reason));
  const root=relationGraphData.nodes.find(n=>n.id===value.source&&n.navigable)||relationGraphData.nodes.find(n=>n.id===value.target&&n.navigable);
  if(root)box.append(relButton('Detail a správa vztahů',async()=>{if(!await canLeaveWorkspaceEditors())return;await openRegisteredProject(root.id);await openProjectRelations();}));
 }
}
document.querySelector('#sidebar-project-graph').addEventListener('click',()=>openRelationGraph().catch(error=>document.querySelector('#relation-graph-status').textContent=error.message));
document.querySelector('#relation-graph-scope').addEventListener('change',refreshRelationGraph);
document.querySelector('#relation-graph-refresh').addEventListener('click',refreshRelationGraph);
for(const [id,delta] of [['out',-.1],['in',.1],['reset',0]])document.querySelector('#relation-graph-'+id).addEventListener('click',()=>{relationGraphZoom=delta?Math.max(.5,Math.min(2,Math.round((relationGraphZoom+delta)*10)/10)):1;applyRelationGraphZoom();});
'''
