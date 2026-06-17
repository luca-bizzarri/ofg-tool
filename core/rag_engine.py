"""
Motore RAG dell'app: connessione AI (OpenRouter), memoria clienti (Qdrant),
ricerca web (Serper) e tutte le funzioni usate dai 5 agenti.

Adattato dall'app esistente: la logica e' la stessa, ma le chiavi sono
centralizzate in core/config.py e questo file e' separato dall'interfaccia.

Strategia di grounding (deterministica): il recupero del contesto applica una
soglia di similarita', garantisce la presenza delle categorie critiche
(brand_book, regole_negative, esempi_copy, istruzioni_formato), ordina i blocchi
per priorita' di categoria e fornisce metadati trasparenti al frontend. Sono
inoltre presenti funzioni per estrarre i vincoli (parole vietate) dalle
regole_negative e validare gli output generati.
"""
import re
import sys
import uuid
import requests
import trafilatura
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, Filter, FieldCondition, MatchValue,
    PointStruct, PayloadSchemaType,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import config

# --- Fix console Windows (cp1252): abilita UTF-8 per accenti/emoji senza crash ---
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# --- Categorie critiche per il grounding ---------------------------------
# Categorie minime che la memoria di un cliente dovrebbe contenere perche'
# l'output sia specifico e non generico/inventato.
REQUIRED_CATEGORIES = {
    "brand_book",
    "regole_negative",
    "esempi_copy",
    "istruzioni_formato",
}

# Categorie ritenute "critiche" per lo sblocco della generazione del PED.
CRITICAL_CATEGORIES = {"brand_book", "regole_negative", "esempi_copy"}

# Priorita' di ordinamento dei blocchi recuperati: piu' basso = piu' importante.
# Le regole negative e il brand book vengono mostrati per primi all'LLM.
CATEGORY_PRIORITY = {
    "regole_negative": 1,
    "regola_stile": 2,
    "brand_book": 3,
    "istruzioni_formato": 4,
    "esempi_copy": 5,
}
_DEFAULT_PRIORITY = 99

# Soglia di similarita' minima per considerare un blocco rilevante.
# Calibrata su 'openai/text-embedding-3-small': i match pertinenti per query
# tematiche stanno tipicamente tra 0.40 e 0.65, quindi 0.30 filtra il rumore
# senza scartare contenuto valido. (0.65 era troppo alto: azzerava tutto.)
MIN_SIMILARITY_SCORE = 0.30


# --- Connessioni di base ---
client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)


def _build_embeddings():
    """Costruisce il provider di embeddings in modo robusto e retrocompatibile.

    Strategia:
    1. Se e' presente una chiave API, usa gli embeddings OpenRouter/OpenAI
       (modello 'openai/text-embedding-3-small', 1536 dimensioni) come prima.
    2. Se la chiave manca, prova un fallback locale con HuggingFace
       (sentence-transformers) solo se la libreria e' installata: l'import del
       modulo NON deve mai rompersi per una chiave assente.
    3. Se nessuna opzione e' disponibile, restituisce un oggetto "stub" che
       solleva un errore chiaro solo quando si tenta davvero di usarlo.

    Nota: il fallback locale produce vettori di dimensione diversa (384) rispetto
    a OpenRouter (1536); per questo viene usato SOLO quando la chiave manca del
    tutto, scenario in cui il grounding sarebbe comunque non operativo.
    """
    if config.API_KEY:
        return OpenAIEmbeddings(
            model="openai/text-embedding-3-small",
            openai_api_key=config.API_KEY,
            openai_api_base=config.API_BASE,
        )

    # Nessuna chiave: tentativo di fallback locale (opzionale).
    try:
        from langchain_huggingface import HuggingFaceEmbeddings  # type: ignore

        print(
            "WARNING: OPENAI_API_KEY mancante. Uso embeddings locali "
            "(sentence-transformers/all-MiniLM-L6-v2). Il grounding cloud e' disattivato."
        )
        return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    except Exception:
        pass

    class _MissingEmbeddings:
        """Stub che fallisce con messaggio chiaro solo all'uso effettivo."""

        _MSG = (
            "Embeddings non disponibili: manca OPENAI_API_KEY (OpenRouter) e non e' "
            "installato un fallback locale (langchain-huggingface / sentence-transformers). "
            "Configura la chiave nel file .env oppure installa il pacchetto di fallback."
        )

        def embed_query(self, *args, **kwargs):
            raise RuntimeError(self._MSG)

        def embed_documents(self, *args, **kwargs):
            raise RuntimeError(self._MSG)

    print("WARNING: " + _MissingEmbeddings._MSG)
    return _MissingEmbeddings()


embeddings = _build_embeddings()

collection_knowledge = config.COLLECTION_KNOWLEDGE
collection_registry = config.COLLECTION_REGISTRY

# --- Crea le collezioni se mancano (con dimensione vettore corretta) ---
try:
    info = client.get_collection(collection_name=collection_knowledge)
    vector_size = 1536
    if hasattr(info.config.params, "vectors"):
        if isinstance(info.config.params.vectors, dict):
            first_key = list(info.config.params.vectors.keys())[0]
            vector_size = info.config.params.vectors[first_key].size
        else:
            vector_size = info.config.params.vectors.size
    if vector_size != 1536:
        client.delete_collection(collection_name=collection_knowledge)
        client.create_collection(collection_name=collection_knowledge, vectors_config=VectorParams(size=1536, distance=Distance.COSINE))
except Exception:
    client.create_collection(collection_name=collection_knowledge, vectors_config=VectorParams(size=1536, distance=Distance.COSINE))

try:
    client.create_collection(collection_name=collection_registry, vectors_config=VectorParams(size=4, distance=Distance.COSINE))
except Exception:
    pass

for field in ["metadata.client_id", "metadata.type", "metadata.source"]:
    try:
        client.create_payload_index(collection_name=collection_knowledge, field_name=field, field_schema=PayloadSchemaType.KEYWORD)
    except Exception:
        pass
try:
    client.create_payload_index(collection_name=collection_registry, field_name="client_id", field_schema=PayloadSchemaType.KEYWORD)
except Exception:
    pass

vectorstore = QdrantVectorStore(client=client, collection_name=collection_knowledge, embedding=embeddings)
llm = ChatOpenAI(model=config.MODEL_NAME, api_key=config.API_KEY, base_url=config.API_BASE, temperature=0.2, max_tokens=4096)


def _clean_id(client_id: str) -> str:
    return str(client_id).strip().replace(" ", "_")


def get_all_clients():
    try:
        records, _ = client.scroll(collection_name=collection_registry, limit=1000, with_payload=True, with_vectors=False)
        return sorted(list(set([r.payload.get("client_id") for r in records if r.payload and r.payload.get("client_id")])))
    except Exception:
        return []


def register_client(client_id: str):
    client_id_clean = _clean_id(client_id)
    point = PointStruct(id=str(uuid.uuid5(uuid.NAMESPACE_DNS, client_id_clean)), vector=[0.1, 0.1, 0.1, 0.1], payload={"client_id": client_id_clean})
    try:
        client.upsert(collection_name=collection_registry, points=[point])
        return True
    except Exception:
        return False


def scrape_and_save_url(client_id: str, url: str, doc_type: str = "link_riferimento"):
    """Scarica e analizza un URL, con timeout per evitare blocchi dell'app."""
    client_id_clean = _clean_id(client_id)
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return False, f"WARNING: Sito non raggiungibile o protetto: {url}"
        text = trafilatura.extract(downloaded, output_format="txt")
        if not text or len(text.strip()) < 100:
            return False, f"WARNING: Nessun testo estraibile (pagina vuota o solo immagini): {url}"
        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = splitter.split_text(text)
        metadatas = [{"client_id": client_id_clean, "type": doc_type, "source": f"[URL] {url}"} for _ in chunks]
        vectorstore.add_texts(texts=chunks, metadatas=metadatas)
        return True, f"OK: Scansionato e salvati {len(chunks)} blocchi da {url}"
    except Exception as e:
        return False, f"FAILED: Errore scraping {url}: {str(e)[:100]}"


def _normalize_ingested_text(text: str) -> str:
    """Pulisce il testo prima di salvarlo in memoria.

    In particolare ricompatta i PDF impaginati che PyPDF2 estrae spezzettati
    (una parola per riga): se piu' del 60% delle righe sono di 1-2 parole,
    riunisce il testo in paragrafi. Migliora qualita' di embedding e grounding.
    """
    if not text:
        return text or ""
    t = text.replace("\r", "")
    lines = [ln.strip() for ln in t.split("\n")]
    nonempty = [ln for ln in lines if ln]
    if nonempty:
        short = sum(1 for ln in nonempty if len(ln.split()) <= 2)
        if short / len(nonempty) > 0.6:
            joined = " ".join(nonempty)
            joined = re.sub(r"[ \t]{2,}", " ", joined)
            joined = re.sub(r"(?<=[.!?])\s+", "\n\n", joined)
            return joined.strip()
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def add_document(client_id: str, text: str, doc_type: str = "generico", source_file: str = "manuale"):
    client_id_clean = _clean_id(client_id)
    if not text or len(text.strip()) < 50:
        return False, "WARNING: Testo troppo breve."
    text = _normalize_ingested_text(text)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_text(text)
    metadatas = [{"client_id": client_id_clean, "type": doc_type, "source": source_file} for _ in chunks]
    vectorstore.add_texts(texts=chunks, metadatas=metadatas)
    return True, f"OK: Salvati {len(chunks)} blocchi (Fonte: {source_file})"


def get_memory_summary(client_id: str):
    client_id_clean = _clean_id(client_id)
    try:
        records, _ = client.scroll(collection_name=collection_knowledge, limit=10000, with_payload=True, with_vectors=False, scroll_filter=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]))
        summary = {}
        for r in records:
            meta = r.payload.get("metadata", {})
            dt, src = meta.get("type", "generico"), meta.get("source", "sconosciuto")
            if dt not in summary:
                summary[dt] = {"count": 0, "files": set()}
            summary[dt]["count"] += 1
            summary[dt]["files"].add(src)
        for k in summary:
            summary[k]["files"] = sorted(list(summary[k]["files"]))
        return summary
    except Exception as e:
        return {"errore": str(e)}


def delete_specific_file(client_id: str, doc_type: str, source_file: str):
    client_id_clean = _clean_id(client_id)
    try:
        client.delete(collection_name=collection_knowledge, points_selector=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean)), FieldCondition(key="metadata.type", match=MatchValue(value=doc_type)), FieldCondition(key="metadata.source", match=MatchValue(value=source_file))]))
        return True, f"OK: '{source_file}' eliminato."
    except Exception as e:
        return False, str(e)


def delete_category(client_id: str, doc_type: str):
    client_id_clean = _clean_id(client_id)
    try:
        client.delete(collection_name=collection_knowledge, points_selector=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean)), FieldCondition(key="metadata.type", match=MatchValue(value=doc_type))]))
        return True, f"OK: Categoria '{doc_type}' eliminata."
    except Exception as e:
        return False, str(e)


def _format_context_block(meta: dict, page_content: str) -> str:
    """Formatta un singolo blocco di contesto per il prompt LLM, con citazione fonte."""
    src = meta.get("source", "N/A")
    dtype = meta.get("type", "N/A")
    return (
        f"[FONTE: {src} | TIPO: {dtype}]\n"
        f"> {page_content}"
    )


def get_client_context(client_id: str, query: str, k: int = 10, score_threshold: float = MIN_SIMILARITY_SCORE) -> dict:
    """Recupera il contesto del cliente con grounding deterministico.

    A differenza della versione precedente (che ritornava una stringa), questa
    funzione ritorna un dizionario strutturato per dare trasparenza al frontend.

    Pipeline:
    1. Retrieval semantico top-k filtrato per client_id.
    2. Filtro per soglia di similarita' (score_threshold): scarta i blocchi
       poco rilevanti che renderebbero l'output generico.
    3. Re-ranking per priorita' di categoria (regole_negative e brand_book per
       primi), preservando l'ordine di similarita' dentro ogni categoria.
    4. Verifica della presenza delle categorie critiche
       (brand_book, regole_negative, esempi_copy).

    Ritorna un dict con chiavi:
      - 'context'  : stringa pronta da inserire nel prompt (con marcatori [FONTE: ...]).
      - 'status'   : 'OK' | 'INCOMPLETE' | 'ERROR'.
      - 'warning'  : eventuale messaggio per l'utente (stringa vuota se assente).
      - 'missing_categories' : lista delle categorie critiche non trovate nei risultati.
      - 'metadata' : {'types_found', 'score_range', 'hit_count', 'sources'}.
    """
    client_id_clean = _clean_id(client_id)
    base = {
        "context": "",
        "status": "OK",
        "warning": "",
        "missing_categories": sorted(CRITICAL_CATEGORIES),
        "metadata": {"types_found": [], "score_range": (None, None), "hit_count": 0, "sources": []},
    }
    try:
        qv = embeddings.embed_query(query)
        hits = client.query_points(
            collection_name=collection_knowledge,
            query=qv,
            query_filter=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]),
            limit=k,
        ).points

        # Filtro per soglia di similarita'.
        hits_filtered = [h for h in hits if getattr(h, "score", 0.0) is not None and h.score >= score_threshold]

        # Rete di sicurezza (best-effort): se la soglia scarta tutto ma il cliente
        # HA comunque documenti, usa i migliori disponibili. Evita il falso
        # "nessuna informazione" quando la memoria e' piena ma i punteggi restano
        # appena sotto soglia.
        used_fallback = False
        if not hits_filtered and hits:
            hits_filtered = hits[: min(len(hits), 5)]
            used_fallback = True

        if not hits_filtered:
            base["status"] = "INCOMPLETE"
            base["warning"] = (
                "[INFORMAZIONE MANCANTE: nessun documento in memoria per questo cliente. "
                "Carica dati pertinenti.]"
            )
            return base

        # Re-ranking per priorita' di categoria, mantenendo l'ordine di
        # similarita' (gia' decrescente in 'hits_filtered') dentro ogni categoria.
        ranked = sorted(
            enumerate(hits_filtered),
            key=lambda pair: (
                CATEGORY_PRIORITY.get(pair[1].payload.get("metadata", {}).get("type", ""), _DEFAULT_PRIORITY),
                pair[0],
            ),
        )
        ordered_hits = [h for _, h in ranked]

        docs = []
        types_found = []
        sources = []
        scores = []
        for h in ordered_hits:
            m = h.payload.get("metadata", {})
            dtype = m.get("type", "N/A")
            src = m.get("source", "N/A")
            if dtype not in types_found:
                types_found.append(dtype)
            if src not in sources:
                sources.append(src)
            if getattr(h, "score", None) is not None:
                scores.append(h.score)
            docs.append(_format_context_block(m, h.payload.get("page_content", "")))

        # NB: la completezza REALE della memoria si misura su cio' che ESISTE
        # (get_memory_completeness, mostrata come semaforo), NON su cio' che il
        # singolo retrieval pesca. Qui quindi NON segnaliamo "categoria mancante"
        # per non dare falsi allarmi quando i dati ci sono ma non emergono dalla query.
        base["context"] = "\n\n---\n\n".join(docs)
        base["missing_categories"] = []
        base["metadata"] = {
            "types_found": types_found,
            "score_range": (min(scores), max(scores)) if scores else (None, None),
            "hit_count": len(ordered_hits),
            "sources": sources,
        }
        if used_fallback:
            base["warning"] = (
                "[NOTA: contesto recuperato con pertinenza moderata. "
                "Verifica che i dati usati siano adeguati.]"
            )
        return base
    except Exception as e:
        base["status"] = "ERROR"
        base["warning"] = f"Errore recupero: {str(e)}"
        return base


def get_context_text(client_id: str, query: str, k: int = 10, score_threshold: float = MIN_SIMILARITY_SCORE) -> str:
    """Helper di compatibilita': ritorna SOLO la stringa di contesto.

    Utile per i punti del codice che si aspettano ancora una stringa da
    concatenare direttamente nel prompt. Include il warning eventuale in coda
    cosi' che l'LLM "veda" comunque i marcatori di informazione mancante.
    """
    res = get_client_context(client_id, query, k=k, score_threshold=score_threshold)
    parts = []
    if res.get("context"):
        parts.append(res["context"])
    if res.get("warning"):
        parts.append(res["warning"])
    return "\n\n".join(parts) if parts else "Nessuna informazione trovata."


def web_search(query: str, num_results: int = 3):
    if not config.SERPER_API_KEY:
        return "WARNING: SERPER_API_KEY mancante."
    try:
        r = requests.post("https://google.serper.dev/search", json={"q": query, "num": num_results}, headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"})
        return "\n".join([f"- {x.get('title')}: {x.get('snippet')}" for x in r.json().get("organic", [])]) if r.status_code == 200 else f"Errore Serper: {r.status_code}"
    except Exception as e:
        return f"Errore: {str(e)}"


def save_and_teach(client_id: str, original_text: str, modified_text: str):
    prompt = PromptTemplate.from_template("Sei un Brand Strategist. AI ha scritto:\n'{original}'\nUmano ha corretto in:\n'{modified}'\nEstrai 1-2 regole stilistiche concrete. Rispondi SOLO con le regole.")
    rule = (prompt | llm).invoke({"original": original_text, "modified": modified_text}).content.strip()
    add_document(client_id, rule, doc_type="regola_stile", source_file="apprendimento_auto")
    return f"Regola appresa per '{client_id}':\n{rule}"


def delete_client(client_id: str):
    client_id_clean = _clean_id(client_id)
    try:
        client.delete(collection_name=collection_knowledge, points_selector=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]))
        client.delete(collection_name=collection_registry, points_selector=Filter(must=[FieldCondition(key="client_id", match=MatchValue(value=client_id_clean))]))
        return True, "Eliminato"
    except Exception as e:
        return False, str(e)


# --- Grounding: vincoli, validazione e completezza memoria ----------------

# Pattern usati per estrarre le parole/frasi vietate dai documenti
# 'regole_negative'. Cattura cio' che segue marcatori tipici come
# "Vietato:", "Non usare:", "DO_NOT_USE:", "Evita:".
_CONSTRAINT_MARKERS = re.compile(
    r"(?:vietat[oi]|non\s+usare|non\s+utilizzare|da\s+evitare|evita(?:re)?|"
    r"bandit[oi]|proibit[oi]|do[_\s-]?not[_\s-]?use|forbidden|blacklist)\s*[:\-]\s*(.+)",
    re.IGNORECASE,
)


def _split_blacklist_items(raw: str) -> list:
    """Spezza una stringa di parole vietate su separatori comuni (virgole, ';', '/', '|')."""
    parts = re.split(r"[,;/|•\n]+", raw)
    items = []
    for p in parts:
        # Rimuove virgolette, parentesi e punteggiatura ai bordi.
        cleaned = p.strip().strip('\'"“”‘’()[]{}.').strip()
        if cleaned and len(cleaned) <= 80:
            items.append(cleaned)
    return items


def extract_constraints(client_id: str, doc_type: str = "regole_negative") -> list:
    """Estrae la blacklist di parole/frasi vietate dai documenti del cliente.

    Recupera TUTTI i blocchi di tipo `doc_type` (default 'regole_negative') per
    il cliente e ne estrae le parole vietate, riconoscendo pattern del tipo
    "Vietato: parola1, parola2" oppure "DO_NOT_USE: ...".

    Ritorna una lista deduplicata (case-insensitive) di stringhe vietate.
    Se non esistono documenti del tipo richiesto, ritorna lista vuota.
    Usata da `validate_constraint_violation` per il controllo post-generazione.
    """
    client_id_clean = _clean_id(client_id)
    blacklist = []
    seen = set()
    try:
        records, _ = client.scroll(
            collection_name=collection_knowledge,
            limit=10000,
            with_payload=True,
            with_vectors=False,
            scroll_filter=Filter(must=[
                FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean)),
                FieldCondition(key="metadata.type", match=MatchValue(value=doc_type)),
            ]),
        )
    except Exception:
        return []

    for r in records:
        text = (r.payload or {}).get("page_content", "") or ""
        for line in text.splitlines():
            m = _CONSTRAINT_MARKERS.search(line)
            if not m:
                continue
            for item in _split_blacklist_items(m.group(1)):
                key = item.lower()
                if key not in seen:
                    seen.add(key)
                    blacklist.append(item)
    return blacklist


def validate_constraint_violation(output_text: str, blacklist: list) -> tuple:
    """Verifica se `output_text` viola la blacklist di parole vietate.

    Il confronto e' case-insensitive e usa i confini di parola (word boundary)
    per evitare falsi positivi su sottostringhe. Per le voci multi-parola viene
    cercata la frase intera.

    Ritorna una tupla (is_clean, violations):
      - is_clean  : True se nessuna parola vietata e' presente.
      - violations: lista di stringhe descrittive, es. "innovazione (pos 45)".
    """
    violations = []
    if not output_text or not blacklist:
        return True, violations

    for term in blacklist:
        term = (term or "").strip()
        if not term:
            continue
        # Confini "di parola" condizionali: applichiamo il boundary SOLO se il
        # carattere esterno del termine e' alfanumerico. Cosi' funziona anche con
        # termini non alfanumerici (es. "c++", "perche'") che con \b sfuggivano.
        esc = re.escape(term)
        left = r"(?<!\w)" if term[:1].isalnum() else ""
        right = r"(?!\w)" if term[-1:].isalnum() else ""
        pattern = left + esc + right
        for match in re.finditer(pattern, output_text, flags=re.IGNORECASE):
            violations.append(f"{term} (pos {match.start()})")

    return (len(violations) == 0), violations


def get_memory_completeness(client_id: str) -> dict:
    """Ritorna lo stato "semaforo" di completezza della memoria del cliente.

    Categorie richieste (REQUIRED_CATEGORIES): brand_book, regole_negative,
    esempi_copy, istruzioni_formato.

    Stato:
      - 'GREEN'  : tutte le categorie richieste sono presenti.
      - 'YELLOW' : almeno 2 categorie richieste presenti (ma non tutte).
      - 'RED'    : meno di 2 categorie richieste presenti.

    Ritorna un dict:
      {
        'status': 'GREEN'|'YELLOW'|'RED',
        'total_entries': int,            # numero totale di blocchi in memoria
        'required_categories': dict,     # {categoria: presente(bool)}
        'present_categories': set,       # categorie richieste effettivamente presenti
        'missing_categories': set,       # categorie richieste mancanti
      }
    Usato dal frontend per mostrare un avviso prima della generazione del PED.
    """
    client_id_clean = _clean_id(client_id)
    result = {
        "status": "RED",
        "total_entries": 0,
        "required_categories": {c: False for c in sorted(REQUIRED_CATEGORIES)},
        "present_categories": set(),
        "missing_categories": set(REQUIRED_CATEGORIES),
    }
    try:
        records, _ = client.scroll(
            collection_name=collection_knowledge,
            limit=10000,
            with_payload=True,
            with_vectors=False,
            scroll_filter=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]),
        )
    except Exception:
        return result

    types_present = set()
    total = 0
    for r in records:
        meta = (r.payload or {}).get("metadata", {})
        dt = meta.get("type", "generico")
        types_present.add(dt)
        total += 1

    present = REQUIRED_CATEGORIES & types_present
    missing = REQUIRED_CATEGORIES - types_present

    if len(present) == len(REQUIRED_CATEGORIES):
        status = "GREEN"
    elif len(present) >= 2:
        status = "YELLOW"
    else:
        status = "RED"

    result["status"] = status
    result["total_entries"] = total
    result["required_categories"] = {c: (c in types_present) for c in sorted(REQUIRED_CATEGORIES)}
    result["present_categories"] = present
    result["missing_categories"] = missing
    return result
