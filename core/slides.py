"""
core/slides.py — Composizione del MARKDOWN OFG di una presentazione via LLM.

Logica CONDIVISA tra:
  - app/Home.py (pagina "Slide" dentro Streamlit)
  - api.py (endpoint /compose chiamato dallo slide-builder)

Riusa l'LLM gia' configurato in core.rag_engine (OpenRouter) e, opzionalmente,
la memoria di brand del cliente (RAG). Il contratto markdown OFG e' documentato
in slide-builder/SPEC.md.
"""
import re

# Contratto markdown OFG incorporato nel prompt (vedi slide-builder/SPEC.md).
SYSTEM_PROMPT = """Sei un progettista di presentazioni per l'agenzia OFG.
Produci ESCLUSIVAMENTE il markdown OFG di una presentazione: nessuna
spiegazione, nessun commento, NIENTE code-fence (no ```).

FORMATO (contratto rigido):
- Una slide per blocco. I blocchi sono separati da una riga di soli trattini: ---
- La PRIMA riga di ogni blocco e' la direttiva di tipo: ":: tipo".
- Tipi ammessi: cover, section, text, bullets, kpi, quote, image, split, closing, table.
- Titolo: "# Titolo".  Sottotitolo: "## Sottotitolo".
- Paragrafo: una riga di testo libera.  Citazione: "> testo".
- Bullet: "- voce".
- KPI: una riga per metrica nel formato "valore | etichetta" (es: "+38% | crescita ricavi").
- Immagine: "![](img:ID)" dove ID e' UNO degli ID elencati tra le immagini disponibili.
- Inline ammessi: **grassetto**, *corsivo*, ==evidenziato==, `code`.
- Opzionale (modalita' landing): "topic: NomeColonna" per raggruppare slide.

REGOLE DI COMPOSIZIONE:
- Scegli il tipo in base al contenuto: numeri/metriche -> kpi; elenchi -> bullets;
  citazione -> quote; foto a tutta pagina -> image; foto + testo -> split;
  apertura -> cover; chiusura -> closing; separatore di sezione -> section.
- Apri SEMPRE con una slide "cover" e chiudi con una slide "closing".
- USA SOLO gli ID immagine elencati. NON inventare ID. Non lasciare token rotti.
  Se non ci sono immagini adatte, non inserire righe immagine. Non riusare lo
  stesso ID piu' di 2 volte. Le slide image/split DEVONO avere una riga "![](img:ID)" valida.
- Scrivi in ITALIANO, conciso e on-brand. Niente testo segnaposto inutile.
- Rispetta il numero massimo di slide indicato.
"""


def _img_lines(images):
    out = []
    for im in images or []:
        if isinstance(im, dict):
            iid, nm = im.get("id"), im.get("name", "")
        else:
            iid, nm = getattr(im, "id", None), getattr(im, "name", "")
        if iid is not None:
            out.append("- img:%s — %s" % (iid, nm or "immagine"))
    return "\n".join(out) if out else "(nessuna immagine disponibile)"


def build_user_prompt(brief, text, images, telos, ctx, blacklist, max_slides):
    parts = []
    if telos:
        parts += [
            "## IDENTITÀ DI BRAND DEL CLIENTE — RISPETTALA SEMPRE",
            telos,
            "",
        ]
    parts += [
        "## OBIETTIVO / BRIEF",
        (brief or "").strip() or "(non fornito)",
        "",
        "## TESTO DI PARTENZA (da strutturare in slide)",
        (text or "").strip() or "(non fornito)",
        "",
        "## IMMAGINI DISPONIBILI (usa SOLO questi ID)",
        _img_lines(images),
    ]
    if ctx:
        parts += ["", "## CONTESTO BRAND (base coerente, non inventare)", ctx]
    parts += ["", "## VINCOLI", "Numero massimo di slide: %d." % int(max_slides or 12)]
    if blacklist:
        parts.append("NON usare mai queste parole/claim: " + ", ".join(blacklist) + ".")
    parts += ["", "Rispondi con il SOLO markdown OFG."]
    return "\n".join(parts)


def strip_fences(md):
    """Rimuove eventuali code-fence e testo di contorno prima del primo blocco."""
    s = (md or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\s*\n([\s\S]*?)\n```$", s)
    if fence:
        s = fence.group(1).strip()
    lines = s.split("\n")
    start = 0
    for idx, line in enumerate(lines):
        t = line.strip()
        if t.startswith("::") or t.startswith("#") or re.match(r"^-{3,}$", t):
            start = idx
            break
    return "\n".join(lines[start:]).strip()


def compose(brief="", text="", images=None, client_id=None, max_slides=12, use_rag=True):
    """Genera il markdown OFG. Ritorna {markdown, used_image_ids, model}.
    Lancia ValueError se manca sia brief sia testo. Import LAZY di rag_engine
    (inizializza Qdrant) per non appesantire chi importa solo le utility.

    Se client_id e' valorizzato, l'IDENTITA' DI BRAND (telos) viene SEMPRE
    iniettata come contesto deterministico. use_rag attiva in piu' il recupero
    documentale da Qdrant (piu' pesante, opzionale)."""
    if not (brief and brief.strip()) and not (text and text.strip()):
        raise ValueError("Serve almeno un brief o del testo.")

    from core import config
    from core import rag_engine as rag

    telos_txt, ctx, blacklist = "", "", []
    if client_id and str(client_id).strip():
        # TELOS: sempre presente, costa solo una lettura del profilo.
        try:
            from core import clients
            telos_txt = clients.telos_text(clients.get_profile(client_id).get("telos"))
        except Exception:
            telos_txt = ""
        try:
            blacklist = rag.extract_constraints(client_id) or []
        except Exception:
            blacklist = []
        # Memoria documentale (Qdrant): opzionale.
        if use_rag:
            query = (brief or text or "")[:500]
            try:
                ctx = rag.get_context_text(client_id, query) or ""
            except Exception:
                ctx = ""

    prompt = SYSTEM_PROMPT + "\n\n" + build_user_prompt(
        brief, text, images or [], telos_txt, ctx, blacklist, max_slides
    )
    raw = rag.llm.invoke(prompt).content
    markdown = strip_fences(raw)
    used = sorted(set(re.findall(r"img:([A-Za-z0-9_-]+)", markdown)))
    return {"markdown": markdown, "used_image_ids": used, "model": config.MODEL_NAME}
