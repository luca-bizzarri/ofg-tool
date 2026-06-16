"""
Motore RAG dell'app: connessione AI (OpenRouter), memoria clienti (Qdrant),
ricerca web (Serper) e tutte le funzioni usate dai 5 agenti.

Adattato dall'app esistente: la logica e' la stessa, ma le chiavi sono
centralizzate in core/config.py e questo file e' separato dall'interfaccia.
"""
import uuid
import requests
import trafilatura
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import PromptTemplate
from langchain_qdrant import Qdrant
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance, VectorParams, Filter, FieldCondition, MatchValue,
    PointStruct, PayloadSchemaType,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core import config

# --- Connessioni di base ---
client = QdrantClient(url=config.QDRANT_URL, api_key=config.QDRANT_API_KEY)

embeddings = OpenAIEmbeddings(
    model="openai/text-embedding-3-small",
    openai_api_key=config.API_KEY,
    openai_api_base=config.API_BASE,
)

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

vectorstore = Qdrant(client=client, collection_name=collection_knowledge, embeddings=embeddings)
llm = ChatOpenAI(model=config.MODEL_NAME, api_key=config.API_KEY, base_url=config.API_BASE, temperature=0.2)


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
        downloaded = trafilatura.fetch_url(url, timeout=10)
        if not downloaded:
            return False, f"⚠️ Sito non raggiungibile o protetto: {url}"
        text = trafilatura.extract(downloaded, output_format="txt")
        if not text or len(text.strip()) < 100:
            return False, f"⚠️ Nessun testo estraibile (pagina vuota o solo immagini): {url}"
        splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
        chunks = splitter.split_text(text)
        metadatas = [{"client_id": client_id_clean, "type": doc_type, "source": f"🌐 {url}"} for _ in chunks]
        vectorstore.add_texts(texts=chunks, metadatas=metadatas)
        return True, f"✅ Scansionato e salvati {len(chunks)} blocchi da {url}"
    except Exception as e:
        return False, f"❌ Errore scraping {url}: {str(e)[:100]}"


def add_document(client_id: str, text: str, doc_type: str = "generico", source_file: str = "manuale"):
    client_id_clean = _clean_id(client_id)
    if not text or len(text.strip()) < 50:
        return False, "⚠️ Testo troppo breve."
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)
    chunks = splitter.split_text(text)
    metadatas = [{"client_id": client_id_clean, "type": doc_type, "source": source_file} for _ in chunks]
    vectorstore.add_texts(texts=chunks, metadatas=metadatas)
    return True, f"✅ Salvati {len(chunks)} blocchi (Fonte: {source_file})"


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
        return True, f"✅ '{source_file}' eliminato."
    except Exception as e:
        return False, str(e)


def delete_category(client_id: str, doc_type: str):
    client_id_clean = _clean_id(client_id)
    try:
        client.delete(collection_name=collection_knowledge, points_selector=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean)), FieldCondition(key="metadata.type", match=MatchValue(value=doc_type))]))
        return True, f"✅ Categoria '{doc_type}' eliminata."
    except Exception as e:
        return False, str(e)


def get_client_context(client_id: str, query: str, k: int = 10):
    client_id_clean = _clean_id(client_id)
    try:
        qv = embeddings.embed_query(query)
        hits = client.query_points(collection_name=collection_knowledge, query=qv, query_filter=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]), limit=k).points
        if not hits:
            return "Nessuna informazione trovata."
        docs = []
        for h in hits:
            m = h.payload.get("metadata", {})
            docs.append(f"📄 **Fonte:** `{m.get('source', 'N/A')}` | **Tipo:** `{m.get('type', 'N/A')}`\n> {h.payload.get('page_content', '')}")
        return "\n\n---\n\n".join(docs)
    except Exception as e:
        return f"Errore recupero: {str(e)}"


def web_search(query: str, num_results: int = 3):
    if not config.SERPER_API_KEY:
        return "⚠️ SERPER_API_KEY mancante."
    try:
        r = requests.post("https://google.serper.dev/search", json={"q": query, "num": num_results}, headers={"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"})
        return "\n".join([f"- {x.get('title')}: {x.get('snippet')}" for x in r.json().get("organic", [])]) if r.status_code == 200 else f"Errore Serper: {r.status_code}"
    except Exception as e:
        return f"Errore: {str(e)}"


def save_and_teach(client_id: str, original_text: str, modified_text: str):
    prompt = PromptTemplate.from_template("Sei un Brand Strategist. AI ha scritto:\n'{original}'\nUmano ha corretto in:\n'{modified}'\nEstrai 1-2 regole stilistiche concrete. Rispondi SOLO con le regole.")
    rule = (prompt | llm).invoke({"original": original_text, "modified": modified_text}).content.strip()
    add_document(client_id, rule, doc_type="regola_stile", source_file="apprendimento_auto")
    return f"🧠 Regola appresa per '{client_id}':\n{rule}"


def delete_client(client_id: str):
    client_id_clean = _clean_id(client_id)
    try:
        client.delete(collection_name=collection_knowledge, points_selector=Filter(must=[FieldCondition(key="metadata.client_id", match=MatchValue(value=client_id_clean))]))
        client.delete(collection_name=collection_registry, points_selector=Filter(must=[FieldCondition(key="client_id", match=MatchValue(value=client_id_clean))]))
        return True, "Eliminato"
    except Exception as e:
        return False, str(e)
