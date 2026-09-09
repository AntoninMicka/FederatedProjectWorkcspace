"""Static, same-origin PoC UI. No project content or credentials in these assets."""
from spikes.local_api import Handler

HTML = '''<!doctype html><html lang="cs"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Projektový workspace</title><link rel="stylesheet" href="/app.css">
<body><aside><div class="brand">◈ &nbsp; WORKSPACE</div><div class="nav">Přehled uzlu</div>
<p>DESKTOPOVÝ EXPERIMENT<br>M0 · Lokální propojení</p></aside>
<main><header><span class="badge">Lokální uzel</span><span>PoC / bez ukládání dat</span></header>
<h1>Váš lokální workspace.</h1><p class="intro">První krok ke společnému prostoru pro projekty, znalosti a rozhodnutí.</p>
<section><div class="eyebrow">OVĚŘENÍ SPOJENÍ</div><h2>Okno a backend spolu komunikují.</h2>
<p>Tlačítko odešle požadavek lokálnímu backendu. Číslo potvrzuje přijaté požadavky v tomto běhu.</p>
<div class="controls"><button id="increment">Ověřit spojení</button><output id="count">0</output></div>
<p id="status" role="status" aria-live="polite">Připraveno k ověření.</p></section>
<div class="next"><h3>Co bude následovat</h3><p>Otevření projektu · Artefakty a metadata · Historie změn</p></div>
<footer>Čítač se po zavření vynuluje. Projektová data, LLM a federace zatím nejsou zapojené.</footer>
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
ASSETS = {'/': ('text/html; charset=utf-8', HTML), '/app.css': ('text/css; charset=utf-8', CSS),
          '/app.js': ('text/javascript; charset=utf-8', JS)}


class DesktopHandler(Handler):
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
