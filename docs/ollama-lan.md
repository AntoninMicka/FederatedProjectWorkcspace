<!--
SPDX-FileCopyrightText: 2026 Antonín Mička
SPDX-License-Identifier: MPL-2.0
-->

# Ollama na privátní síti

Workspace rozlišuje Ollamu na stejném počítači (`same-node`) od služby na
jiném stroji v LAN (`private-network`). LAN server není „lokální“ ve smyslu
privacy hranice: obsah `local-only` jej nikdy nesmí opustit. Podporovaný klient
nepoužívá DNS, redirect ani nešifrované HTTP do sítě.

## Podporovaná topologie

```text
Workspace
  -> https://PRIVATE_IP:TLS_PORT
  -> TLS reverse proxy na Ollama serveru
  -> http://127.0.0.1:11434
  -> Ollama
```

Ollama standardně poslouchá na `127.0.0.1:11434`. Oficiální dokumentace
umožňuje změnu přes `OLLAMA_HOST` a popisuje provoz za reverse proxy, ale pro
tento Workspace je doporučené ponechat Ollamu na loopbacku a do vymezené LAN
vystavit pouze HTTPS proxy. Přímé `OLLAMA_HOST=0.0.0.0:11434` je sice možné,
ale nesplňuje zdejší požadavek HTTPS a certifikátového pinu.

- [Ollama FAQ — vystavení serveru a proxy](https://docs.ollama.com/faq)
- [Ollama API — lokální base URL](https://docs.ollama.com/api/introduction)
- [Ollama API — generate](https://docs.ollama.com/api/generate)

Minimální tvar Nginx konfigurace je například:

```nginx
server {
    listen PRIVATE_IP:11443 ssl;
    server_name _;

    ssl_certificate     /etc/ollama-proxy/tls.crt;
    ssl_certificate_key /etc/ollama-proxy/tls.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    location / {
        proxy_pass http://127.0.0.1:11434;
        proxy_set_header Host 127.0.0.1:11434;
        proxy_buffering off;
    }
}
```

Placeholdery `PRIVATE_IP` a cesty k certifikátu je nutné nahradit skutečnými
hodnotami. Firewall má povolit zvolený TLS port pouze z konkrétního Workspace
uzlu nebo z nezbytně úzkého správcovského subnetu. Workspace v této verzi
neposílá Basic Auth ani klientský mTLS certifikát. Ollama lokální API samo
autentizaci nevyžaduje; samotný TLS pin proto nenahrazuje omezení firewallu.

### Ollama uvnitř Open WebUI Docker image

Pokud Ollama běží uvnitř kontejneru `open-webui` a TLS proxy v samostatném
kontejneru, proxy nesmí používat svůj vlastní loopback. Oba kontejnery připojte
do jedné uživatelské Docker sítě a použijte interní jméno služby:

```nginx
location / {
    resolver 127.0.0.11 valid=10s;
    set $ollama_upstream http://open-webui:11434;
    proxy_pass $ollama_upstream;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;
}
```

Na hostiteli má být nešifrované API publikované pouze na loopbacku, zatímco
HTTPS proxy může poslouchat na LAN adrese:

```text
127.0.0.1:11434 -> open-webui:11434
LAN_IP:11443    -> ollama-tls-proxy:443 -> open-webui:11434
```

AI Production Studio tento režim připraví volbou **Zpřístupnit Ollama API přes
TLS reverse proxy**. Po změně je nutné řízeně znovu vytvořit `open-webui` i proxy
a aktualizovat exportované systemd unity; pouhý restart starého kontejneru
nezmění jeho publikované porty. Pojmenované volumes s modely a Open WebUI daty
se při tomto znovuvytvoření zachovají. Výsledek ověřte například:

```sh
docker ps --format '{{.Names}} {{.Ports}}' \
  --filter name=open-webui --filter name=ollama-tls-proxy
```

Kontrola nesmí u `open-webui` ukázat `0.0.0.0:11434` ani `[::]:11434`. Pokud je
HTTPS proxy dostupná celé důvěryhodné LAN, omezte navíc její port hostitelským
firewallem na přesnou zdrojovou IP Omnie. Alternativní Nginx `allow`/`deny`
může být druhá vrstva, ne náhrada kontroly hostitelského firewallu.

## Kontrola serveru

Nejdřív ověřte proxy běžným TLS klientem proti důvěryhodné CA, bez `-k`:

```sh
curl --fail --show-error --cacert /cesta/ca.crt \
  https://PRIVATE_IP:11443/api/tags
```

Serverový certifikát musí mít `PRIVATE_IP` v IP SAN. Certifikát pouze pro
`localhost` nestačí pro nezávislou CA validaci z Omnie, i kdyby přes proxy
technicky prošel klient používající jen přesný leaf pin.

SHA-256 pin, který Workspace očekává, je hash přes DER bajty aktuálního leaf
certifikátu:

```sh
openssl s_client -connect PRIVATE_IP:11443 </dev/null 2>/dev/null \
  | openssl x509 -outform DER \
  | sha256sum
```

Výstupní hex řetězec má přesně 64 malých znaků. Pin je veřejný identifikátor
certifikátu, nikoli tajný klíč. Po legitimní rotaci certifikátu se spojení
záměrně odmítne, dokud správce nezíská nový pin jiným důvěryhodným kanálem a
vědomě neupraví binding.

Pole přijme také běžný výstup OpenSSL ve tvaru
`SHA256 Fingerprint=68:34:...`: prefix, dvojtečky a velikost písmen Workspace
před validací normalizuje. Pokud uložení přesto selže, vyplněné hodnoty zůstanou
jako node-local neaktivní koncept i po obnovení stránky nebo restartu. Poslední
platný binding se konceptem nemění a dál je jediným nastavením použitelným pro
LLM běhy.

Pro **ID cíle** vytvořte jednou stabilní UUID, například `uuidgen`, a uchovejte
je jako identitu této služby i při běžném restartu. UUID není autentizační
doklad; kryptografickou vazbu na dosažený endpoint v této verzi poskytuje
přesný certifikátový pin. Výměna stroje nebo služby má dostat nové ID.

## Nastavení Workspace

V **Nastavení -> AI backend** vyplňte:

1. **Hranice:** `Privátní síť`.
2. **Endpoint:** číselná privátní adresa, například
   `https://192.168.1.50:11443`.
3. **Model:** přesný název z `/api/tags`, včetně tagu.
4. **ID cíle:** stabilní UUID služby.
5. **SHA-256 certifikátu:** pin získaný výše.

Tlačítko **Ověřit bez uložení** provede pouze `GET /api/tags`. Neposílá prompt,
projektová data ani Context Manifest a nemění poslední potvrzený binding. Teprve
**Uložit backend** atomicky publikuje node-local konfiguraci mimo projektový
Git. Test dostupnosti není souhlas s odesláním konkrétního projektu.

Potvrzený `private-network` binding lze použít také v režimu **Orchestrace**.
Každý nový orchestrační request nese jeho přesné `binding_id` a revizi; backend
je před sestavením Context Manifestu porovná s aktuální konfigurací. Pokud se
mezitím změnil endpoint, model, cíl, pin nebo revize, požadavek se odmítne a UI
zachová zadání pro vědomý nový běh. Síťový binding se nikdy nepřeznačí na
`same-node`, obsah `local-only` se neodešle a nedostupnost neaktivuje jiný model
ani provider.

## Diagnostika a nový pokus

Workspace rozlišuje alespoň nedostupný endpoint, timeout při spojení, chybu TLS,
neshodný pin, zakázaný redirect, chybějící model, přetížení, HTTP odmítnutí,
neplatný JSON, neplatnou Ollama obálku, příliš velkou odpověď a přerušený
transport. Chyba před odesláním nebo jednoznačná odpověď skončí jako `failed`.
Timeout či přerušení po zahájení generačního requestu skončí jako durable
`unknown`, protože model mohl práci provést, i když odpověď nedorazila.

Původní `unknown` run se nikdy automaticky neopakuje. UI ponechá zadání a výběr
kontextu a umožní uživateli tlačítkem **Zpracovat** vědomě vytvořit nový run s
novými identitami. Nedochází ke skrytému přepnutí na externího providera.

Přímý brainstorming používá bounded NDJSON streaming. Timeout prvního rámce,
idle timeout nebo ztráta spojení po odeslání jsou rovněž `unknown`; průběžný
text je jen UI projekce a nevytváří zprávu. Ruční ověření popisuje
[checklist streamované Ollamy](ollama-streaming-acceptance.md). Orchestrace a
role workflow zůstávají na celistvé odpovědi a jejich recovery kontrakt se
nemění.

## Hranice současné akceptace

Automatické testy používají řízený transport a ověřují pin před requestem,
restart konfigurace a journalu, přesný orchestrační výběr bindingu, změnu revize,
privacy, jednotlivé chybové kategorie a zákaz opakování `unknown` runu.
Dokud není zvlášť zaznamenán živý test na skutečném LAN serveru, nejde o důkaz
firewallu, konkrétní reverse proxy, certifikačního procesu ani dostupnosti po
restartu fyzického stroje.
