"""
Onboarding automatico di un nuovo cliente.

Legge il sito web, i social e gli asset del cliente (URL), ne estrae il testo e
fa generare all'AI un PROFILO strutturato (brand, tono di voce, ICP, esempi di
copy, regole negative) gia' pronto per essere salvato nella memoria dell'app.

Flusso: URL -> scraping (trafilatura) -> sintesi AI in JSON -> revisione umana
-> salvataggio nelle categorie di memoria corrette.
"""
import json
import re

import trafilatura

from core import rag_engine as rag


# Chiavi del profilo e mappatura verso le categorie di memoria dell'app.
PROFILE_KEYS = ["brand_positioning", "tono_di_voce", "icp_personas", "esempi_copy", "regole_negative"]

PROFILE_LABELS = {
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


def scrape_urls(urls, max_chars_per=4000):
    """Scarica e estrae il testo da una lista di URL.

    Ritorna una lista di tuple (url, testo|None, stato). I social protetti o le
    pagine JS spesso danno poco testo: in quel caso testo=None e stato lo spiega.
    """
    results = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                results.append((url, None, "non raggiungibile o protetto"))
                continue
            txt = (trafilatura.extract(downloaded, output_format="txt") or "").strip()
            if len(txt) < 80:
                results.append((url, None, "poco testo estraibile (pagina protetta/JS)"))
            else:
                results.append((url, txt[:max_chars_per], "ok"))
        except Exception as e:
            results.append((url, None, f"errore: {str(e)[:60]}"))
    return results


def generate_profile(client_id, material_text, note=""):
    """Fa generare all'AI il profilo cliente in JSON dalle fonti raccolte.

    Restituisce sempre un dict con tutte le PROFILE_KEYS (stringhe). Dove l'AI
    non ha abbastanza informazioni inserisce '[DA COMPLETARE A MANO]'.
    """
    material_text = (material_text or "")[:12000]  # limite per non sprecare token
    prompt = (
        f"Sei un brand strategist senior. Analizza i contenuti (sito/social/asset) del cliente "
        f"'{client_id}' qui sotto e crea un profilo per impostare la memoria di uno strumento di "
        f"scrittura AI. Rispondi SOLO con un JSON valido con ESATTAMENTE queste chiavi (valori "
        f"stringa, in italiano, ricchi e SPECIFICI del cliente, mai generici):\n"
        '{\n'
        '  "brand_positioning": "chi e\' il brand, cosa fa, valori, proposta di valore, mercato",\n'
        '  "tono_di_voce": "come scrive il brand: registro, se da del tu o del lei, stile, parole tipiche, cosa evitare, con 1-2 formule di esempio",\n'
        '  "icp_personas": "cliente ideale, bisogni, pain e gain principali",\n'
        '  "esempi_copy": "2-3 esempi di copy brevi nello stile del brand, pronti all\'uso",\n'
        '  "regole_negative": "cosa NON fare o dire; eventuali parole vietate nel formato -> Vietato: parola1, parola2"\n'
        '}\n\n'
        f"CONTENUTI RACCOLTI:\n{material_text}\n\n"
        f"NOTE AGGIUNTIVE DELL'OPERATORE: {note or '(nessuna)'}\n\n"
        f"REGOLE: NON inventare fatti non presenti nelle fonti. Se un'informazione non e' "
        f"deducibile, scrivi '[DA COMPLETARE A MANO]' SOLO per quella chiave. Niente testo fuori dal JSON."
    )
    raw = rag.llm.invoke(prompt).content
    clean = raw.strip()
    clean = re.sub(r"^```(?:json)?\s*", "", clean)
    clean = re.sub(r"\s*```$", "", clean)
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        clean = m.group(0)
    try:
        data = json.loads(clean)
    except Exception:
        data = {}
    return {k: str(data.get(k, "") or "").strip() for k in PROFILE_KEYS}


def save_profile(client_id, profile):
    """Salva le voci del profilo nelle categorie di memoria corrette.

    Salta le voci vuote o segnate come '[DA COMPLETARE A MANO]'. Ritorna (salvate, dettagli).
    """
    salvate = 0
    dettagli = []
    for key in PROFILE_KEYS:
        val = (profile.get(key) or "").strip()
        if not val or "[DA COMPLETARE" in val.upper() or len(val) < 50:
            dettagli.append(f"saltato {PROFILE_LABELS[key]} (vuoto o troppo corto)")
            continue
        ok, msg = rag.add_document(client_id, val, doc_type=_DOCTYPE[key], source_file="onboarding_auto")
        if ok:
            salvate += 1
            dettagli.append(f"OK {PROFILE_LABELS[key]} -> {_DOCTYPE[key]}")
        else:
            dettagli.append(f"errore {PROFILE_LABELS[key]}: {msg}")
    return salvate, dettagli
