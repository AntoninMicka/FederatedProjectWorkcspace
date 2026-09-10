"""Static same-origin UI; project data arrives through authenticated reads."""
import sqlite3
import subprocess

from spikes.local_api import Handler
from spikes.projects import Projects
from spikes.storage import StaleIndex
from spikes.workspace import PendingOperation

HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projektový workspace</title><link rel="stylesheet" href="/app.css">
<body><aside><div class="brand">◈ &nbsp; WORKSPACE</div><div class="nav">Přehled uzlu</div>
<div id="todo-widget" aria-labelledby="todo-heading"><h2 id="todo-heading">Hlavní TODO</h2>
<p id="todo-status" role="status">Otevřete projekt.</p><div id="todo-title"></div>
<ul id="todo-tree" aria-label="Položky hlavního TODO"></ul>
<small>Pouze pro čtení · upravíte v editoru</small></div>
<p>DESKTOPOVÝ EXPERIMENT<br>M1 · Projekty</p></aside>
<main><header><span class="badge">Lokální uzel</span><span>PoC / lokální projekty</span></header>
<h1>Váš lokální workspace.</h1><p class="intro">První krok ke společnému prostoru pro projekty, znalosti a rozhodnutí.</p>
<section><div class="eyebrow">PROJEKTY</div><h2>Otevřít projekt</h2>
<label for="projects">Registrovaný projekt</label>
<div class="controls"><select id="projects" aria-label="Registrovaný projekt"></select>
<button id="open-project" disabled>Otevřít</button></div>
<p id="project-status" role="status" aria-live="polite">Načítám registrace…</p>
<div id="project-view" hidden><h2 id="project-title"></h2>
<p>Git commit: <code id="project-commit"></code></p><h3>Artefakty</h3>
<ul id="artifacts"></ul></div></section>
<section><div class="eyebrow">OVĚŘENÍ SPOJENÍ</div><h2>Okno a backend spolu komunikují.</h2>
<p>Tlačítko odešle požadavek lokálnímu backendu. Číslo potvrzuje přijaté požadavky v tomto běhu.</p>
<div class="controls"><button id="increment">Ověřit spojení</button><output id="count">0</output></div>
<p id="status" role="status" aria-live="polite">Připraveno k ověření.</p></section>
<div class="next"><h3>Co bude následovat</h3><p>Metadata · Historie změn</p></div>
<footer>Čítač se po zavření vynuluje. Dokumenty a checklisty upravíte tlačítkem Markdown editor nebo Hlavní TODO v horní liště. LLM a federace zatím nejsou zapojené.</footer>
</main><script src="/app.js"></script></body></html>'''
CSS = '''*{box-sizing:border-box}body{margin:0;background:#f5f7fa;color:#162638;font:16px system-ui;display:flex;min-height:100vh}aside{width:238px;flex-shrink:0;background:#142638;color:#c8d4df;padding:34px 22px}.brand{font-weight:750;letter-spacing:2px;color:white;margin-bottom:52px}.nav{background:#274154;border-radius:8px;padding:13px}aside p{font-size:11px;line-height:2;letter-spacing:1px;margin-top:35px}main{max-width:1100px;width:100%;padding:36px 54px}header{display:flex;justify-content:space-between;align-items:center;color:#627183;font-size:12px}.badge{color:#1c6556;background:#e0efe9;border-radius:20px;padding:8px 13px}h1{font-size:38px;letter-spacing:-1px;margin:50px 0 10px}.intro{color:#627183;line-height:1.7}section{background:white;border:1px solid #dce3e9;border-radius:14px;padding:30px;margin:30px 0}.eyebrow{font-size:11px;color:#31796e;font-weight:750;letter-spacing:2px}h2{font-size:22px}section p{color:#627183;line-height:1.7;max-width:610px}.controls{display:flex;gap:28px;align-items:center;margin-top:24px}button{border:0;border-radius:8px;background:#176b60;color:white;font:600 15px system-ui;padding:14px 23px;cursor:pointer}button:hover{background:#12564d}button:disabled{opacity:.55;cursor:wait}button:focus-visible{outline:3px solid #59b6aa;outline-offset:3px}output{font-size:32px;font-weight:700}#status{font-size:13px}.next{padding:0 4px}.next h3{font-size:15px}.next p,footer{color:#627183;font-size:13px;line-height:1.8}footer{margin-top:40px;border-top:1px solid #dce3e9;padding-top:20px}@media(max-width:780px){aside{width:175px;padding:24px 14px}main{padding:26px}h1{font-size:29px}}'''
JS = '''const button=document.querySelector('#increment');
button.addEventListener('click',async()=>{
 button.disabled=true;
 const status=document.querySelector('#status');
 status.textContent='Ověřuji spojení…';
 try {
  const response=await fetch('/v1/counter',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({action:'increment'}),signal:AbortSignal.timeout(4000)});
  if(!response.ok) throw new Error('request rejected');
  const result=await response.json();
  document.querySelector('#count').textContent=result.value;
  status.textContent='Spojení funguje. Backend přijal požadavek.';
 }catch(error){status.textContent='Spojení se nezdařilo. Zavřete a znovu spusťte aplikaci.';}
 finally{button.disabled=false;}
});'''
JS += """
const projects=document.querySelector('#projects');
const openProject=document.querySelector('#open-project');
const projectStatus=document.querySelector('#project-status');
const projectView=document.querySelector('#project-view');
const artifacts=document.querySelector('#artifacts');
const todoTree=document.querySelector('#todo-tree');
const todoStatus=document.querySelector('#todo-status');
let viewRequest=0;
function renderTodo(todo){
 todoTree.replaceChildren();
 document.querySelector('#todo-title').textContent=todo?.title || '';
 if(!todo){todoStatus.textContent='Hlavní TODO zatím není vytvořeno.';return;}
 if(todo.status!=='ready'){todoStatus.textContent='Hlavní TODO nelze zobrazit v tomto formátu nebo velikosti.';return;}
 todoStatus.textContent=todo.total ? `${todo.completed} z ${todo.total} hotovo` : 'Zatím bez položek checklistu.';
 if(todo.truncated) todoStatus.textContent+=' Zobrazeno prvních 1000 položek.';
 const lists=[todoTree];
 for(let i=0;i<todo.items.length;i++){
  const item=todo.items[i];lists.length=item.depth+1;
  const row=document.createElement('li');row.dataset.depth=item.depth;
  const label=document.createElement('span');label.className='todo-label';
  const check=document.createElement('input');check.type='checkbox';check.checked=item.checked;check.disabled=true;
  check.setAttribute('aria-label',item.checked ? 'Hotovo' : 'Nehotovo');
  const title=document.createElement('span');title.className='todo-text';title.textContent=item.title;
  label.append(check,title);
  if(item.checked) row.classList.add('todo-done');
  if(todo.items[i+1]?.depth>item.depth){
   const branch=document.createElement('details');branch.open=true;
   const summary=document.createElement('summary');summary.append(label);branch.append(summary);
   const children=document.createElement('ul');branch.append(children);row.append(branch);
   lists[item.depth+1]=children;
  }else{row.append(label);}
  lists[item.depth].append(row);
 }
}
function clearProject(){
 ++viewRequest;
 todoTree.replaceChildren();document.querySelector('#todo-title').textContent='';
 todoStatus.textContent='Otevřete projekt.';
 projectView.hidden=true;
 document.querySelector('#project-title').textContent='';
 document.querySelector('#project-commit').textContent='';
 artifacts.replaceChildren();
}
async function projectRequest(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(body),signal:AbortSignal.timeout(60000)});
 const result=await response.json();
 if(!response.ok) throw new Error(result.error || 'Požadavek byl odmítnut.');
 return result;
}
projects.addEventListener('change',()=>{clearProject();projectStatus.textContent='Projekt připraven k otevření.';});
openProject.addEventListener('click',async()=>{
 clearProject();const request=viewRequest;const projectId=projects.value;
 openProject.disabled=true;projects.disabled=true;
 projectStatus.textContent='Otevírám projekt…';
 try{
  const result=await projectRequest('/v1/projects/open',{project_id:projectId});
  if(request!==viewRequest || projects.value!==projectId) return;
  renderTodo(result.main_todo);
  document.querySelector('#project-title').textContent=result.title;
  document.querySelector('#project-commit').textContent=result.commit_id;
  for(const item of result.artifacts){
   const row=document.createElement('li');row.textContent=item.title+' · '+item.id;artifacts.append(row);
  }
  projectView.hidden=false;
  projectStatus.textContent=result.artifacts.length ? 'Projekt otevřen.' : 'Projekt zatím nemá artefakty.';
 }catch(error){if(request===viewRequest){projectStatus.textContent=error.message;todoStatus.textContent='TODO není dostupné. Zkuste projekt znovu otevřít.';}}
 finally{if(request===viewRequest){openProject.disabled=false;projects.disabled=false;}}
});
let catalogRequest=0;
async function loadProjects(selectedId=null){
 const request=++catalogRequest;
 clearProject();openProject.disabled=true;projects.disabled=true;
 try{
  const result=await projectRequest('/v1/projects',{});
  if(request!==catalogRequest) return;
  projects.replaceChildren();
  for(const project of result.projects){
   const option=document.createElement('option');option.value=project.id;option.textContent=project.id;projects.append(option);
  }
  openProject.disabled=!result.projects.length;projects.disabled=false;
  projectStatus.textContent=result.projects.length ? 'Vyberte projekt a otevřete jej.' :
   'Zatím nemáte žádný projekt. Použijte tlačítko Nový projekt v horní liště.';
  if(selectedId && result.projects.some(p=>p.id===selectedId)){
   projects.value=selectedId;openProject.click();
  }
 }catch(error){if(request===catalogRequest){projectStatus.textContent=error.message;projects.disabled=false;}}
}
loadProjects();
"""
CSS += 'select{max-width:100%;padding:12px}code,li{overflow-wrap:anywhere}li{margin:12px 0}.controls{flex-wrap:wrap}'
CSS += '''#todo-widget{margin-top:32px}#todo-widget h2{font-size:17px;color:white;margin:0 0 12px}
#todo-widget p{font-size:12px;line-height:1.5;letter-spacing:0;margin:8px 0;color:#c8d4df}
#todo-title{font-size:13px;font-weight:600;overflow-wrap:anywhere}#todo-widget small{font-size:11px;color:#aabecf}
#todo-tree{max-height:55vh;overflow:auto;padding:0;margin:14px 0;list-style:none}
#todo-tree ul{padding-left:14px;list-style:none;border-left:1px solid #496072;margin-left:4px}
#todo-tree li{font-size:13px;margin:8px 0}#todo-tree summary{cursor:pointer}
.todo-label{display:inline-flex;gap:7px;align-items:baseline;max-width:100%}
.todo-label input{flex-shrink:0;accent-color:#79c9ac}.todo-text{overflow-wrap:anywhere;min-width:0}
.todo-done> .todo-label .todo-text,.todo-done>details>summary .todo-text{color:#a9c5b7;text-decoration:line-through}
#todo-tree summary:focus-visible{outline:2px solid #79c9ac;outline-offset:3px}'''
ASSETS = {'/': ('text/html; charset=utf-8', HTML), '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS)}


class DesktopHandler(Handler):
    post_paths = Handler.post_paths | {'/v1/projects', '/v1/projects/open'}

    def dispatch(self, request):
        if self.path == '/v1/counter':
            return super().dispatch(request)
        projects = self.server.projects or Projects()
        try:
            if self.path == '/v1/projects' and request == {}:
                return self.reply(200, {'projects': projects.list()})
            if (self.path == '/v1/projects/open' and isinstance(request, dict)
                    and set(request) == {'project_id'} and isinstance(request['project_id'], str)):
                return self.reply(200, projects.open(request['project_id']))
            return self.send_error(400)
        except PendingOperation:
            return self.reply(409, {'error': 'Projekt má nedokončenou operaci. Nejprve proveďte obnovu.'})
        except StaleIndex:
            return self.reply(409, {'error': 'Projekt se během čtení změnil. Zkuste jej znovu otevřít.'})
        except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
            # Do not forward paths, Git stderr or configuration payloads to the renderer.
            return self.reply(422, {'error': 'Projekt nelze otevřít: ověřte konfiguraci, registraci, '
                                   'práva lokálního stavu a platnost Git dat/indexu.'})

    def do_GET(self):
        if self.single('Host') != self.server.authority:
            return self.send_error(403)
        if self.path not in ASSETS:
            return self.send_error(404)
        kind, content = ASSETS[self.path]
        data = content.encode()
        self.close_connection = True
        self.send_response_only(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(data)
