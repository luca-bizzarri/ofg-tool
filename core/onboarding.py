"""
Onboarding automatico di un nuovo cliente.

Legge sito + social del cliente (CRAWLING anche delle sotto-pagine dello stesso
dominio) e gli asset/caption forniti, e fa generare all'AI un PROFILO completo:
brand, tono di voce, ICP, esempi di copy, regole negative, LINGUE e RUBRICHE
suggerite. Il tutto viene salvato nella memoria (testi) e nella scheda cliente
(rubriche + lingue) per guidare la generazione del PED.
"""
import json
import re
from urllib.parse import urljoin, urlparse

import trafilatura

from core import rag_engine as rag
from core import clients


# Campi testuali del profilo -> categoria di memoria
TEXT_KEYS = ["brand_positioning", "tono_di_voce", "icp_personas", "esempi_copy", "regole_negative"]
TEXT_LABELS = {
    "brand_positioning": "📘 Brand / Posizionamento",
    "tono_di_voce": "🗣️ Tono di Voce / Come scrivere",
    "icp_personas": "👤 ICP / Cliente ideale (Pain & Gain)",
    "esempi_copy": "✍️ Esempi di Copy nello stile del brand",
    "regole_negative": "🚫 Regole Negative (cosa NON fare)",
}
_DOCTYPE = {
    "brand_positioning": "brand_book",
    "tono_di_voce": "istruzioni_creazione",
    "icp_personas": "icp_personas",
    "esempi_copy": "esempi_copy",
    "regole_negative": "regole_negative",
}

_SKIP_EXT = re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|mp4|mov|css|js|ico|woff2?)(\?|$)", re.I)


def crawl_urls(start_urls, max_pages=12, max_chars_per=4000):
    """Scarica gli URL forniti E le loro SOTTO-PAGINE (stesso dominio), in BFS.

    Ritorna lista di (url, testo|None, stato). I social protetti danno poco testo:
    in quel caso il testo va incollato a mano in fase di onboarding.
    """
    visited = set()
    results = []
    queue = [(u.strip(), u.strip()) for u in start_urls if u and u.strip()]
    while queue and len(results) < max_pages:
        url, seed = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        try:
            html = trafilatura.fetch_url(url)
            if not html:
                results.append((url, None, "non raggiungibile/protetto"))
                continue
            text = (trafilatura.extract(html, output_format="txt") or "").strip()
            if len(text) >= 80:
                results.append((url, text[:max_chars_per], "ok"))
            else:
                results.append((url, None, "poco testo (pagina protetta/JS)"))
            # Coda delle sotto-pagine interne (stesso dominio del seed)
            base_dom = urlparse(seed).netloc
            if base_dom and len(results) + len(queue) < max_pages * 3:
                for href in re.findall(r'href=["\']([^"\']+)["\']', html):
                    nu = urljoin(url, href.split("#")[0])
                    pd = urlparse(nu)
                    if pd.scheme in ("http", "https") and pd.netloc == base_dom and nu not in visited:
                        if not _SKIP_EXT.search(nu):
                            queue.append((nu, seed))
        except Exception as e:
            results.append((url, None, f"errore: {str(e)[:50]}"))
    return results


def _repair_truncated_json(s: str) -> str:
    """Ripara (best-effort) un JSON troncato dal limite di token: chiude la
    stringa e le parentesi rimaste aperte, cosi' i campi gia' emessi sono
    recuperabili anche se l'output e' stato tagliato a meta'."""
    out = []
    stack = []
    in_str = False
    escaped = False
    for ch in s:
        out.append(ch)
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack:
                    stack.pop()
    text = "".join(out)
    if in_str:                      # stringa lasciata aperta: la chiudo
        text += '"'
    # tolgo una eventuale coda penzolante: '"chiave":' senza valore (il due punti
    # e' obbligatorio, cosi' NON tocco i valori-stringa gia' chiusi dalla riparazione)
    text = re.sub(r'[\s,]*"[^"]*"\s*:\s*$', "", text)
    # tolgo anche una chiave a meta' appena dopo una virgola/graffa (senza due punti)
    text = re.sub(r'([{,])\s*"[^"]*"\s*$', r"\1", text)
    text = re.sub(r"[\s,]+$", "", text)
    for opener in reversed(stack):  # chiudo le parentesi ancora aperte
        text += "}" if opener == "{" else "]"
    return text


def _parse_json(raw):
    clean = (raw or "").strip()
    # via i blocchi di ragionamento dei modelli "reasoning" (chiusi o troncati)
    clean = re.sub(r"<think>.*?</think>", "", clean, flags=re.DOTALL | re.IGNORECASE)
    clean = re.sub(r"<think>.*$", "", clean, flags=re.DOTALL | re.IGNORECASE)
    # via i fence markdown
    clean = re.sub(r"^```(?:json)?\s*", "", clean.strip())
    clean = re.sub(r"\s*```$", "", clean)
    start = clean.find("{")
    if start == -1:
        return {}
    clean = clean[start:]
    # 1) tentativo diretto: dal primo '{' all'ultimo '}'
    end = clean.rfind("}")
    if end != -1:
        try:
            return json.loads(clean[:end + 1])
        except Exception:
            pass
    # 2) tentativo su output troncato: riparo le parentesi/stringhe aperte
    try:
        return json.loads(_repair_truncated_json(clean))
    except Exception:
        return {}


def generate_profile(client_id, material_text, note=""):
    """Genera con l'AI il profilo completo (testi + lingue + rubriche) in JSON.

    Ritorna un dict con TEXT_KEYS + 'languages' (lista) + 'rubriche' (lista di dict).
    """
    material_text = (material_text or "")[:16000]
    prompt = (
        f"Sei un brand strategist senior. Analizza i contenuti (sito/social/asset) del cliente "
        f"'{client_id}' e crea un profilo per uno strumento di scrittura AI. Rispondi SOLO con JSON "
        f"valido, valori in italiano, ricchi e SPECIFICI del cliente (mai generici):\n"
        "{\n"
        '  "brand_positioning": "chi e\' il brand, cosa fa, valori, proposta di valore, mercato",\n'
        '  "tono_di_voce": "registro, se da del tu/lei, stile, parole tipiche, cosa evitare, 1-2 formule esempio",\n'
        '  "icp_personas": "cliente ideale, bisogni, pain e gain principali",\n'
        '  "esempi_copy": "2-3 esempi di copy brevi nello stile del brand",\n'
        '  "regole_negative": "cosa NON fare/dire; parole vietate nel formato -> Vietato: parola1, parola2",\n'
        '  "languages": ["IT"]  (metti ["IT","EN"] solo se il brand comunica anche in inglese),\n'
        '  "rubriche": [ {"nome":"...", "descrizione":"a cosa serve la rubrica", "taglio":"obiettivo/angolo tipico", "tipologia":"reel|post|carousel|stories", "esempi":"esempi di contenuti"} ]\n'
        "}\n"
        f"Proponi 4-6 RUBRICHE social sensate e distintive per questo brand (format editoriali ricorrenti).\n\n"
        f"CONTENUTI RACCOLTI (sito + sotto-pagine + asset):\n{material_text}\n\n"
        f"NOTE OPERATORE: {note or '(nessuna)'}\n\n"
        f"REGOLE: NON inventare fatti non presenti. Se un'info manca scrivi '[DA COMPLETARE A MANO]' "
        f"solo per quella chiave. Niente testo fuori dal JSON."
    )
    # Il modello free e' instabile (reasoning che tronca, rate-limit 429): puo'
    # restituire JSON vuoto/parziale. Ritento finche' non ottengo qualcosa di
    # sostanzioso o esaurisco i tentativi. 'reinforce' rende il prompt piu' secco
    # ai giri successivi per ridurre il reasoning e far uscire prima il JSON.
    reinforce = "\n\nIMPORTANTE: rispondi SUBITO col JSON completo, senza ragionare a voce, senza testo prima o dopo."
    data = {}
    last_err = ""
    for attempt in range(3):
        try:
            raw = rag.llm.invoke(prompt + (reinforce if attempt else "")).content
            data = _parse_json(raw)
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:120]}"
            data = {}
        # riuscito se almeno un campo testuale e' pieno oppure ha proposto rubriche
        if any(len(str(data.get(k) or "").strip()) >= 40 for k in TEXT_KEYS) or data.get("rubriche"):
            break
    out = {k: str(data.get(k, "") or "").strip() for k in TEXT_KEYS}
    # segnale per la UI: profilo di fatto vuoto (tutti i tentativi falliti)
    out["_empty"] = not (any(out[k] for k in TEXT_KEYS) or data.get("rubriche"))
    out["_error"] = last_err
    langs = data.get("languages") or ["IT"]
    out["languages"] = [l for l in langs if l in ("IT", "EN")] or ["IT"]
    rubriche = []
    for r in (data.get("rubriche") or []):
        if isinstance(r, dict) and r.get("nome"):
            rubriche.append(clients.new_rubrica(
                nome=str(r.get("nome", "")).strip(),
                descrizione=str(r.get("descrizione", "")).strip(),
                taglio=str(r.get("taglio", "")).strip(),
                tipologia=str(r.get("tipologia", "reel")).strip().lower(),
                esempi=str(r.get("esempi", "")).strip(),
            ))
    out["rubriche"] = rubriche
    return out


def save_profile(client_id, profile):
    """Salva il profilo: testi -> memoria; lingue + rubriche -> scheda cliente.

    Ritorna (n_blocchi_memoria, dettagli).
    """
    salvate = 0
    dettagli = []
    for key in TEXT_KEYS:
        val = (profile.get(key) or "").strip()
        if not val or "[DA COMPLETARE" in val.upper() or len(val) < 50:
            dettagli.append(f"saltato {TEXT_LABELS[key]} (vuoto/corto)")
            continue
        ok, _ = rag.add_document(client_id, val, doc_type=_DOCTYPE[key], source_file="onboarding_auto")
        if ok:
            salvate += 1
            dettagli.append(f"OK {TEXT_LABELS[key]}")
    # scheda cliente: lingue + rubriche
    card = clients.get_profile(client_id)
    if profile.get("languages"):
        card["languages"] = profile["languages"]
    if profile.get("rubriche"):
        card["rubriche"] = profile["rubriche"]
    clients.save_profile(client_id, card)
    dettagli.append(f"Scheda cliente aggiornata: lingue {card['languages']}, {len(card.get('rubriche', []))} rubriche")
    return salvate, dettagli
