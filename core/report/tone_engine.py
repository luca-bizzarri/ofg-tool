# -*- coding: utf-8 -*-
"""
Motore di tono: genera i TESTI MORBIDI del report (considerazioni, insight dei
KPI, conclusioni, direzione) a partire dai SOLI dati estratti, ancorati al
brand del cliente (TELOS + memoria Qdrant).

Filosofia (feedback Marco Aspesi): tono consulenziale e arrotondato, le
valutazioni si fanno NEL TEMPO, niente allarmi da un solo mese, niente
raccomandazioni tecniche operative al cliente (sono lavoro interno), mai
inventare numeri.

Pipeline:
1. stesura (LLM, JSON) con le regole di tono cablate;
2. ammorbidimento (secondo passaggio LLM) che toglie allarmi/imperativi/reco
   tecniche interne;
3. controllo anti invenzione: ogni numero citato nel testo deve esistere nei
   dati; i sospetti finiscono in `_tone_warnings` (l'operatore decide).
"""
import json
import re

from core import rag_engine as rag
from core import clients


# Regole di tono, cablate nel prompt (vedi memoria report-tono-morbido).
TONE_RULES = """REGOLE DI TONO (TASSATIVE):
1. Tono consulenziale, arrotondato, equilibrato: ne' troppo entusiasta ne' troppo negativo. Si SPIEGA al cliente.
2. Le valutazioni si fanno NEL TEMPO: un calo o una salita di un solo mese NON significano che qualcosa "si e' rotto" o che il pubblico e' "saturo". VIETATE le parole: rotto, saturo, critico, allarme, fermare subito.
3. Ogni variazione va CONTESTUALIZZATA: un calo va letto come fisiologico dopo periodi alti, con possibili spiegazioni esterne (stagionalita', nuovi competitor, mix di contenuti). Mai come emergenza.
4. NIENTE raccomandazioni tecniche operative (alza il budget, metti il tracking, ferma l'adset, ottimizza la campagna): sono lavoro interno dell'agenzia, NON vanno nel report. Resta su letture e direzione editoriale di alto livello.
5. Niente imperativi d'urgenza: mai "fermare immediatamente", semmai "da osservare nei prossimi due o tre mesi".
6. Usa SOLO i numeri presenti nei dati forniti. Non inventare nulla. Se un dato manca, non citarlo.
7. Niente trattini lunghi nel testo: usa le virgole."""


def _fnum(x):
    return "" if x is None else str(x)


def _facts_block(ch):
    """Riassunto testuale dei SOLI dati certi, da passare all'LLM."""
    L = []
    meta = ch.get("meta", {})
    L.append(f"Canale: {meta.get('channel','')} | Periodo: {meta.get('period','')}")
    if ch.get("kpis"):
        L.append("\nKPI (id | etichetta | valore | variazione):")
        for k in ch["kpis"]:
            L.append(f"- {k['id']} | {k['label']} | {k['value']} | {k['delta']}")
    if ch.get("engagement_breakdown"):
        L.append("\nEngagement (organico/paid/totale/variazione):")
        for e in ch["engagement_breakdown"]:
            L.append(f"- {e['label']}: org {_fnum(e.get('organic'))}, paid {_fnum(e.get('paid'))}, tot {_fnum(e.get('total'))}, var {e.get('variation','')}")
    if ch.get("rates"):
        for r in ch["rates"]:
            L.append(f"- {r['metric']}: organico {r['organic']}, paid {r['paid']}, totale {r['total']}, var {r['variation']}")
    if ch.get("audience_growth"):
        L.append("\nCrescita follower: " + ", ".join(f"{a['label']} {a['value']}" for a in ch["audience_growth"]))
    if ch.get("publishing_mix"):
        L.append("\nMix pubblicazione: " + ", ".join(f"{m['format']} {m['posts']} ({m['variation']})" for m in ch["publishing_mix"]))
    if ch.get("top_content"):
        L.append("\nTop content:")
        for c in ch["top_content"]:
            L.append(f"- {c.get('date','')} {c.get('type','')} \"{c.get('topic','')}\": views {c.get('views')}, reach {c.get('reach')}, eng {c.get('engagement')}, saved {c.get('saved')}, ER reach {c.get('er_reach')}%")
    if ch.get("hashtags"):
        L.append("\nHashtag top: " + ", ".join(f"{h['tag']} ({h['value']})" for h in ch["hashtags"][:6]))
    if ch.get("community"):
        L.append("\nCommunity: " + ", ".join(f"{c['label']} {c['value']} ({c['variation']})" for c in ch["community"]))
    # --- campi specifici LinkedIn ---
    if ch.get("follower_growth"):
        L.append("\nNuovi follower per tipologia: " + ", ".join(f"{g['label']} {g['value']}" for g in ch["follower_growth"]))
    if ch.get("audience"):
        for dim, rows in ch["audience"].items():
            if rows:
                L.append(f"Audience follower per {dim}: " + ", ".join(f"{r['label']} {r['value']}" for r in rows[:5]))
    if ch.get("visitors_kpis"):
        L.append("\nVisite pagina: " + ", ".join(f"{k['label']} {k['value']}" for k in ch["visitors_kpis"]))
    if ch.get("visitor_audience"):
        for dim, rows in ch["visitor_audience"].items():
            if rows:
                L.append(f"Visitatori per {dim}: " + ", ".join(f"{r['label']} {r['value']}" for r in rows[:5]))
    if ch.get("top_post"):
        L.append("\nTop post LinkedIn:")
        for p in ch["top_post"]:
            L.append(f"- {p.get('date','')} \"{p.get('topic','')}\": impressioni {p.get('impressions')}, clic {p.get('clicks')}, commenti {p.get('comments')}")
    if ch.get("missing_data"):
        L.append("\nDati NON disponibili (non citarli come fossero noti): " + "; ".join(ch["missing_data"]))
    return "\n".join(L)


# Schema JSON richiesto all'LLM (chiavi stabili usate dal template).
_SCHEMA = """{
  "considerazioni": {
    "generale": ["1-2 paragrafi di lettura generale del mese, equilibrata"],
    "soft_index": [{"title": "etichetta breve", "desc": "frase soft", "value": "un valore PRESO dai dati"}],
    "performance": "lettura delle performance (1 paragrafo)",
    "forza": "punti di forza (1 paragrafo)",
    "attenzione": "aree da osservare nel tempo (1 paragrafo, tono pacato)",
    "sintesi": "sintesi conclusiva (1 paragrafo)"
  },
  "kpi_insights": {"<id_kpi>": {"detail": "lettura soft del dato, contestualizzata", "action": "indicazione editoriale di alto livello, NON tecnica operativa"}},
  "insight_centrale": {"quote": "una frase sintetica", "body": "1 paragrafo di approfondimento"},
  "conclusioni": {
    "lettura": ["2-3 paragrafi di lettura conclusiva"],
    "direzione": [{"title": "direzione editoriale", "desc": "descrizione soft, alto livello"}]
  },
  "roadmap": {
    "continuare": ["azioni EDITORIALI da continuare (alto livello, non tecniche)"],
    "potenziare": ["aree editoriali da potenziare"],
    "correggere": [],
    "testare": ["eventuali idee di format da testare, soft"]
  }
}"""


def _brand_ctx(client_id, use_rag):
    telos = clients.telos_for(client_id) if client_id else ""
    ctx = ""
    if client_id and use_rag:
        try:
            ctx = rag.get_context_text(client_id, "tono di voce, posizionamento, pubblico, settore", k=8)
        except Exception:
            ctx = ""
    parts = []
    if telos:
        parts.append("IDENTITA' DI BRAND (TELOS):\n" + telos)
    if ctx and "Nessuna informazione" not in ctx:
        parts.append("CONTESTO CLIENTE (memoria):\n" + ctx)
    return "\n\n".join(parts) if parts else "(nessun contesto brand disponibile)"


def _invoke(prompt):
    """Chiama l'LLM con un tetto di token piu' alto (i report multi-sezione
    possono essere lunghi); fallback al client standard se bind non supportato."""
    try:
        return rag.llm.bind(max_tokens=8000).invoke(prompt).content
    except Exception:
        return rag.llm.invoke(prompt).content


def _parse_json(raw):
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", (raw or "").strip())
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    cand = m.group(0) if m else clean
    try:
        return json.loads(cand)
    except Exception:
        pass
    # riparazione: tronca all'ultima graffa bilanciata (toglie coda sporca)
    depth, end = 0, -1
    for i, c in enumerate(cand):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
    if end > 0:
        try:
            return json.loads(cand[:end + 1])
        except Exception:
            return {}
    return {}


def _draft(ch, client_id, use_rag):
    kpi_ids = [k["id"] for k in ch.get("kpis", [])]
    prompt = (
        f"Sei un consulente social senior che scrive il commento di un report mensile per il CLIENTE.\n\n"
        f"{_brand_ctx(client_id, use_rag)}\n\n"
        f"{TONE_RULES}\n\n"
        f"DATI CERTI DEL PERIODO (usa SOLO questi numeri):\n{_facts_block(ch)}\n\n"
        f"Per i kpi_insights usa esattamente questi id: {kpi_ids}.\n"
        f"Rispondi SOLO con JSON valido in italiano, con questa struttura:\n{_SCHEMA}"
    )
    for _ in range(2):  # un retry: l'LLM a volte risponde con testo non valido
        out = _parse_json(_invoke(prompt))
        if out:
            return out
    return {}


def _soften(narrative, client_id):
    """Secondo passaggio: ammorbidisce e toglie reco tecniche/allarmi/imperativi."""
    prompt = (
        f"Sei un revisore editoriale. Riscrivi il seguente JSON di commenti per un report social RENDENDOLO PIU' MORBIDO.\n\n"
        f"{TONE_RULES}\n\n"
        f"Interventi richiesti: togli ogni allarme e imperativo d'urgenza; trasforma le eventuali raccomandazioni tecniche "
        f"operative (budget, tracking, adset, ottimizzazioni) in letture editoriali di alto livello o eliminale; "
        f"contestualizza i cali nel tempo. NON aggiungere numeri nuovi. Mantieni ESATTAMENTE le stesse chiavi JSON.\n\n"
        f"JSON da ammorbidire:\n{json.dumps(narrative, ensure_ascii=False)}\n\n"
        f"Rispondi SOLO con il JSON ammorbidito."
    )
    out = _parse_json(_invoke(prompt))
    return out or narrative


def _allowed_numbers(ch):
    """Insieme dei numeri 'leciti' (presenti nei dati), per il controllo anti invenzione."""
    nums = set()
    for m in re.finditer(r"\d+(?:[.,]\d+)?", json.dumps(ch, ensure_ascii=False)):
        nums.add(m.group(0).replace(".", ",").rstrip(",0").rstrip(","))
    return nums


def _check_numbers(narrative, ch):
    allowed = _allowed_numbers(ch)
    text = json.dumps(narrative, ensure_ascii=False)
    suspicious = []
    for m in re.finditer(r"\d+(?:[.,]\d+)?", text):
        tok = m.group(0)
        norm = tok.replace(".", ",").rstrip(",0").rstrip(",")
        if norm and norm not in allowed and tok not in ("01", "02", "03", "04", "05"):
            suspicious.append(tok)
    return sorted(set(suspicious))


def generate(channel, client_id="", use_rag=True, soften=True):
    """Genera i testi morbidi e li applica al canale. Ritorna il canale arricchito.

    Aggiunge:
      channel['narrative'] = {hero, considerazioni, insight_centrale, conclusioni}
      riempie detail/action di ogni KPI, insight delle rates, e channel['roadmap']
      channel['_tone_warnings'] = lista di numeri sospetti (non nei dati)
    """
    try:
        narrative = _draft(channel, client_id, use_rag)
        if not narrative:
            channel["_tone_warnings"] = ["Generazione non riuscita: nessun testo prodotto."]
            return channel
        if soften:
            narrative = _soften(narrative, client_id)

        # KPI insights -> detail/action
        kins = narrative.get("kpi_insights", {}) or {}
        for k in channel.get("kpis", []):
            ins = kins.get(k["id"]) or {}
            k["detail"] = ins.get("detail", k.get("detail", ""))
            k["action"] = ins.get("action", k.get("action", ""))

        # insight centrale -> prima riga delle rates (insight) se vuota
        ic = narrative.get("insight_centrale", {}) or {}
        rates = channel.get("rates", [])
        if rates and not rates[0].get("insight"):
            rates[0]["insight"] = ic.get("quote", "")

        # roadmap (solo liste non vuote)
        rm = narrative.get("roadmap", {}) or {}
        if any(rm.get(k) for k in ("continuare", "potenziare", "correggere", "testare")):
            channel["roadmap"] = {k: list(rm.get(k) or []) for k in ("continuare", "potenziare", "correggere", "testare")}

        channel["narrative"] = {
            "hero": (narrative.get("considerazioni", {}) or {}).get("sintesi", ""),
            "considerazioni": narrative.get("considerazioni", {}),
            "insight_centrale": ic,
            "conclusioni": narrative.get("conclusioni", {}),
        }
        channel["_tone_warnings"] = _check_numbers(narrative, channel)
    except Exception as e:
        channel["_tone_warnings"] = [f"Errore generazione testi: {str(e)[:160]}"]
    return channel
