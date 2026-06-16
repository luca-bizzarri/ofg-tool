"""
Configurazione centrale dell'app.
Legge le chiavi API dalle variabili d'ambiente (file .env in locale)
oppure dai "secrets" di Streamlit (quando l'app sara' online).
Le chiavi NON sono mai scritte qui dentro: stanno nel file .env (escluso da Git).
"""
import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()  # carica il file .env quando si lavora in locale


def get_key(key_name: str, default: str = "") -> str:
    """Recupera una chiave da .env oppure dai secrets di Streamlit Cloud."""
    value = os.getenv(key_name)
    if value:
        return value
    try:
        return st.secrets.get(key_name, default)
    except Exception:
        return default


# --- AI / LLM (OpenRouter) ---
API_KEY = get_key("OPENAI_API_KEY")
API_BASE = get_key("OPENAI_API_BASE") or "https://openrouter.ai/api/v1"
MODEL_NAME = get_key("MODEL_NAME") or "qwen/qwen-2.5-72b-instruct"

# --- Database vettoriale / memoria clienti (Qdrant) ---
QDRANT_URL = get_key("QDRANT_URL")
QDRANT_API_KEY = get_key("QDRANT_API_KEY")

# --- Ricerca web competitor (Serper) ---
SERPER_API_KEY = get_key("SERPER_API_KEY")

# --- Nomi delle "collezioni" (tabelle) nel database vettoriale ---
COLLECTION_KNOWLEDGE = "agenzia_knowledge"   # i documenti/memoria dei clienti
COLLECTION_REGISTRY = "client_registry"      # l'elenco dei clienti

# --- Impostazioni prodotto ---
APP_NAME = "OFG Tool"
