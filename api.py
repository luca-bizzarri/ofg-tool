"""
api.py — Micro-servizio HTTP per lo SLIDE-BUILDER (OFG).

Espone un endpoint che, dato un brief e/o del testo libero (piu' l'elenco
delle foto disponibili), fa generare all'AI il MARKDOWN OFG di una
presentazione (vedi contratto in slide-builder/SPEC.md). Riusa l'LLM gia'
configurato dell'app (core.rag_engine.llm -> OpenRouter) e, opzionalmente,
la memoria di brand del cliente (RAG su Qdrant).

NON sostituisce ne' tocca l'app Streamlit (app/Home.py). Gira a parte:

    cd C:\\Users\\lucab\\ofg-tool
    uvicorn api:app --host 127.0.0.1 --port 8800

Dipendenze: fastapi, uvicorn (vedi requirements.txt).
"""
import re
from typing import List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core import config

app = FastAPI(title="OFG Slide Composer", version="1.0")

# Lo slide-builder e' servito in locale su :8000 (un sito https remoto non
# potrebbe comunque chiamare http://localhost per via del mixed-content).
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Modelli richiesta/risposta
# --------------------------------------------------------------------------- #
class ImageRef(BaseModel):
    id: str
    name: str = ""


class ComposeRequest(BaseModel):
    brief: Optional[str] = ""
    text: Optional[str] = ""
    images: List[ImageRef] = []
    client_id: Optional[str] = None
    max_slides: int = 12


class ComposeResponse(BaseModel):
    markdown: str
    used_image_ids: List[str]
    model: str
    sources: List[str] = []


# --------------------------------------------------------------------------- #
# Prompt — incorpora il contratto markdown OFG (vedi slide-builder/SPEC.md)
# --------------------------------------------------------------------------- #
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


def _build_user_prompt(brief, text, images, ctx, blacklist, max_slides):
    if images:
        img_lines = "\n".join("- img:%s — %s" % (i.id, (i.name or "immagine")) for i in images)
    else:
        img_lines = "(nessuna immagine disponibile)"

    parts = [
        "## OBIETTIVO / BRIEF",
        (brief or "").strip() or "(non fornito)",
        "",
        "## TESTO DI PARTENZA (da strutturare in slide)",
        (text or "").strip() or "(non fornito)",
        "",
        "## IMMAGINI DISPONIBILI (usa SOLO questi ID)",
        img_lines,
    ]
    if ctx:
        parts += ["", "## CONTESTO BRAND (base coerente, non inventare)", ctx]
    parts += [
        "",
        "## VINCOLI",
        "Numero massimo di slide: %d." % int(max_slides or 12),
    ]
    if blacklist:
        parts.append("NON usare mai queste parole/claim: " + ", ".join(blacklist) + ".")
    parts += ["", "Rispondi con il SOLO markdown OFG."]
    return "\n".join(parts)


def _strip_fences(md: str) -> str:
    """Rimuove eventuali code-fence e testo di contorno prima del primo blocco."""
    s = (md or "").strip()
    # toglie un eventuale fence ```...``` che avvolge tutto
    fence = re.match(r"^```[a-zA-Z]*\s*\n([\s\S]*?)\n```$", s)
    if fence:
        s = fence.group(1).strip()
    # scarta righe iniziali di "chiacchiera" finche' non si incontra una riga
    # che assomiglia all'inizio di un blocco OFG (direttiva, titolo o separatore)
    lines = s.split("\n")
    start = 0
    for idx, line in enumerate(lines):
        t = line.strip()
        if t.startswith("::") or t.startswith("#") or re.match(r"^-{3,}$", t):
            start = idx
            break
    return "\n".join(lines[start:]).strip()


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    # Leggero: NON importa rag_engine (che inizializza Qdrant).
    return {"status": "ok", "model": config.MODEL_NAME}


@app.post("/compose")
def compose(req: ComposeRequest):
    if not (req.brief and req.brief.strip()) and not (req.text and req.text.strip()):
        return {"error": "Serve almeno un brief o del testo."}, 400

    # Import LAZY: importare rag_engine inizializza Qdrant/embeddings; lo facciamo
    # solo quando serve davvero, cosi' /health resta utile anche se Qdrant e' giu'.
    from core import rag_engine as rag

    ctx = ""
    blacklist = []
    if req.client_id and req.client_id.strip():
        query = (req.brief or req.text or "")[:500]
        try:
            ctx = rag.get_context_text(req.client_id, query) or ""
        except Exception:
            ctx = ""
        try:
            blacklist = rag.extract_constraints(req.client_id) or []
        except Exception:
            blacklist = []

    prompt = SYSTEM_PROMPT + "\n\n" + _build_user_prompt(
        req.brief, req.text, req.images, ctx, blacklist, req.max_slides
    )

    try:
        raw = rag.llm.invoke(prompt).content
    except Exception as e:  # errore di rete / provider
        return {"error": "Generazione fallita: %s" % e}, 502

    markdown = _strip_fences(raw)
    used = sorted(set(re.findall(r"img:([A-Za-z0-9_-]+)", markdown)))

    return ComposeResponse(
        markdown=markdown,
        used_image_ids=used,
        model=config.MODEL_NAME,
        sources=[],
    )
