import streamlit as st
import pandas as pd
import io
import time
import json
import re
import os
import sys

# Windows console UTF-8 fix: evita UnicodeEncodeError su emoji/accenti italiani
# stampati a console (cp1252). Innocuo se stdout non e' riconfigurabile.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Rende importabile la cartella del progetto (per "from core import ...")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import rag_engine as rag
from core import reporting
from core import onboarding

_LOGO_SIDEBAR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "Logo_no payoff_nero.png")

import PyPDF2
import docx
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from fpdf import FPDF
import tempfile


def read_table(uploaded_file):
    """Legge un file caricato come tabella: supporta CSV ed Excel (.xlsx / .xls)."""
    name = (uploaded_file.name or "").lower()
    uploaded_file.seek(0)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(uploaded_file)
    return pd.read_csv(uploaded_file)


def check_password():
    """Gate di accesso con password.

    Attivo SOLO se 'APP_PASSWORD' e' impostata nei Secrets (online). In locale,
    senza secret, l'app resta libera (comodo per sviluppo). Ritorna True se l'accesso
    e' consentito.
    """
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = ""
    if not expected:
        return True  # nessuna password configurata -> nessun gate
    if st.session_state.get("auth_ok"):
        return True
    st.markdown("## 🔒 OFG Tool — Accesso riservato")
    pwd = st.text_input("Password", type="password", key="pwd_input")
    if st.button("Entra", type="primary"):
        if pwd == expected:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("Password errata.")
    return False


def char_counter(text, soft_limit=800):
    """Mostra un contatore di caratteri sotto una casella di testo.

    - Sotto 50: troppo corto per essere salvato.
    - Oltre soft_limit (800 = un blocco): avviso, perche' verra' spezzato in
      piu' blocchi e in generazione rischia il troncamento.
    """
    n = len(text or "")
    if n < 50:
        st.caption(f"🔴 {n} caratteri — servono almeno 50 per salvare")
    elif n > soft_limit:
        st.caption(f"🟠 {n} caratteri — oltre {soft_limit}: verra' diviso in piu' blocchi (meglio accorciare)")
    else:
        st.caption(f"✅ {n}/{soft_limit} caratteri")


def memory_badge(cid):
    """Mini semaforo di completezza memoria, per le schermate dei report.

    Mostra se il cliente ha abbastanza materiale in memoria perche' il report
    sia specifico e non generico. GREEN/YELLOW/RED da get_memory_completeness().
    """
    try:
        comp = rag.get_memory_completeness(cid)
    except Exception:
        return
    s = comp.get("status", "RED")
    miss = sorted(comp.get("missing_categories", []))
    icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(s, "⚪")
    extra = f" · mancano: {', '.join(miss)}" if miss else ""
    st.caption(f"{icon} **Memoria cliente: {s}** · {comp.get('total_entries', 0)} blocchi{extra}")
    if s == "RED":
        st.warning("🔴 Memoria scarsa per questo cliente: il report rischia di essere generico. Carica brand_book, ICP e report precedenti nella sezione **🧠 Memoria**.")


st.set_page_config(page_title="OFG Tool", layout="wide", page_icon="🚀")
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"], .stApp, button, input, textarea, select { font-family: 'Raleway', sans-serif !important; }
    .main-header {font-size: 2.2rem; font-weight: 900; color: #111; margin-bottom: 0.4rem; border-bottom: 5px solid #ffd400; display: inline-block; padding-bottom: 4px;}
    .sub-header {font-size: 1.05rem; color: #555; margin-bottom: 1.3rem;}
    .debug-box {background-color: #1b1b1b; color: #e6e6e6; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 0.85rem; white-space: pre-wrap;}
    .channel-box {background-color: #f5f5f5; padding: 10px; border-radius: 8px; margin-bottom: 5px;}
    .insight-box {background-color: #fffdf0; border-left: 5px solid #ffd400; padding: 15px; border-radius: 6px; margin-bottom: 15px;}
    .context-box {background-color: #fff9e0; border-left: 5px solid #ffd400; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-size: 0.9rem;}
    .stButton>button[kind="primary"] {background-color: #111; border: 2px solid #111;}
    .stButton>button[kind="primary"]:hover {background-color: #ffd400; color: #111; border-color: #ffd400;}
    </style>
""", unsafe_allow_html=True)

# --- Gate password (attivo solo online se APP_PASSWORD e' nei Secrets) ---
if not check_password():
    st.stop()

# ==========================================
# SIDEBAR (CON PULIZIA STATO AL CAMBIO CLIENTE)
# ==========================================
if os.path.exists(_LOGO_SIDEBAR):
    st.sidebar.image(_LOGO_SIDEBAR, use_container_width=True)
st.sidebar.title("OFG Tool")
all_clients = rag.get_all_clients()
client_options = ["➕ CREA NUOVO CLIENTE..."] + all_clients
selected_option = st.sidebar.selectbox("👤 Seleziona Cliente", client_options, key="client_selector")
client_id = ""

if selected_option == "➕ CREA NUOVO CLIENTE...":
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🆕 Nuovo Cliente")
    new_client_id = st.sidebar.text_input("ID Cliente (es. Nike, Mario_Rossi)", key="new_client_input").strip().replace(" ", "_")
    if st.sidebar.button("✅ CREA CLIENTE", type="primary", use_container_width=True):
        if not new_client_id:
            st.sidebar.error("⚠️ Inserisci un ID")
        elif new_client_id in all_clients:
            st.sidebar.warning(f"Il cliente '{new_client_id}' esiste già.")
        else:
            with st.sidebar.spinner("Creazione in corso..."):
                if rag.register_client(new_client_id):
                    rag.add_document(new_client_id, f"Cliente {new_client_id} inizializzato.", doc_type="sistema", source_file="sistema")
                    st.sidebar.success(f"✅ Cliente '{new_client_id}' creato!")
                    time.sleep(1)
                    st.rerun()
else:
    client_id = selected_option
    # FIX FRONTEND: Pulizia stato al cambio cliente per evitare dati incrociati
    # (data leakage multi-client). Reset di tutte le chiavi task-specific.
    if st.session_state.get("_active_client_id") != client_id:
        for _k in ['ped_full_plan', 'ped_batch', 'editable_df', 'ads_cache', 'social_cache']:
            st.session_state.pop(_k, None)
        st.session_state["_active_client_id"] = client_id
    st.sidebar.markdown("---")
    st.sidebar.success(f"🟢 Cliente attivo: **{client_id}**")

if client_id:
    st.sidebar.markdown("---")
    with st.sidebar.expander("⚠️ Elimina Cliente"):
        st.warning(f"Stai per eliminare **TUTTI** i dati di '{client_id}'.")
        confirm_text = st.text_input(f"Per confermare, scrivi: {client_id}", key="delete_confirm")
        if st.button(f"🗑️ ELIMINA '{client_id}'", type="secondary", use_container_width=True):
            if confirm_text.strip() == client_id:
                with st.spinner("Eliminazione in corso..."):
                    success, message = rag.delete_client(client_id)
                    if success:
                        st.success("✅ Eliminato.")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ Errore: {message}")
            else:
                st.error("❌ Testo non corrispondente.")

if not client_id:
    st.markdown('<div class="main-header">Benvenuto in OFG Tool</div>', unsafe_allow_html=True)
    st.info("👈 Seleziona o crea un cliente per iniziare.")
    st.stop()

st.markdown(f'<div class="main-header">Dashboard: {client_id}</div>', unsafe_allow_html=True)
task_type = st.radio("🤖 Scegli l'Agente", [
    "🚀 Onboarding Nuovo Cliente",
    "🧠 Carica e Gestisci Memoria",
    "📅 Piano Editoriale Completo",
    "📊 Report ADS Performance",
    "📱 Report Social Organico",
    "🔍 Analisi Competitor / Trend"
], horizontal=True)
st.markdown("---")

# ==========================================
# AGENTE 1: MEMORIA (CON RIEPILOGO UX)
# ==========================================
if task_type == "🧠 Carica e Gestisci Memoria":
    st.markdown('<div class="sub-header">Alimenta o modifica la memoria strategica del cliente</div>', unsafe_allow_html=True)

    # --- ISTRUZIONI DI FORMATO ---
    with st.expander("📝 Istruzioni Specifiche per Formato (CLICCA PER MODIFICARE)", expanded=False):
        st.info("💡 Definisci le regole di scrittura per ogni formato. L'AI le userà tassativamente durante la generazione.")

        col_inst1, col_inst2 = st.columns(2)
        with col_inst1:
            instr_linkedin = st.text_area("🔵 Istruzioni LinkedIn", height=200, value="Usa ganci (hook) forti nelle prime 2 righe. Spaziatura ampia tra i paragrafi (a capo frequenti). Tono professionale ma conversazionale e umano. Usa elenchi puntati per la leggibilità. Massimo 1-2 emoji per paragrafo. Hashtag solo alla fine (max 3-5). Vietato il corporate speak generico.")
            char_counter(instr_linkedin)
            instr_blog = st.text_area("📝 Istruzioni Blog / Articoli", height=200, value="Struttura SEO: Titolo H1, sottotitoli H2/H3. Paragrafi di 3-4 frasi massimo. Usa storytelling e dati concreti per supportare le tesi. Inserisci una CTA morbida a metà articolo e una forte alla fine. Tono autorevole ed educativo. Lunghezza minima 400 parole.")
            char_counter(instr_blog)
        with col_inst2:
            instr_newsletter = st.text_area("📧 Istruzioni Newsletter", height=200, value="Subject line accattivante e breve (max 50 caratteri). Tono intimo e diretto (usa il 'tu'). Inizia con una storia o un aneddoto personale/aziendale. Vai dritto al punto. Una sola Call To Action (CTA) chiara e visibile. Lunghezza media: 250-400 parole.")
            char_counter(instr_newsletter)
            instr_ig = st.text_area("📸 Istruzioni Instagram (Feed/Reel)", height=200, value="Copy breve e d'impatto (max 150 parole). Prima riga deve fermare lo scroll. Usa emoji in modo strategico per spezzare il testo. Chiudi sempre con una domanda o una CTA per i commenti. Hashtag pertinenti (5-10). Per i Reel, fornisci uno script parlato con indicazione dei tempi.")
            char_counter(instr_ig)

        if st.button("💾 Salva Istruzioni di Formato", type="primary", use_container_width=True):
            rag.add_document(client_id, instr_linkedin, "istruzioni_formato", "regole_linkedin")
            rag.add_document(client_id, instr_blog, "istruzioni_formato", "regole_blog")
            rag.add_document(client_id, instr_newsletter, "istruzioni_formato", "regole_newsletter")
            rag.add_document(client_id, instr_ig, "istruzioni_formato", "regole_instagram")
            st.success("✅ Istruzioni di formato salvate e pronte per l'uso!")

    st.markdown("---")

    # --- MEMORIA ATTUALE CON RIEPILOGO UX ---
    st.markdown("### 📂 Memoria Attuale")

    # --- SEMAFORO COMPLETEZZA MEMORIA ---
    def render_memory_semaforo(cid):
        """Mostra il semaforo di completezza memoria (GREEN/YELLOW/RED).
        Ritorna il dict di completezza per riuso a valle."""
        try:
            comp = rag.get_memory_completeness(cid)
        except Exception as e:
            st.warning(f"⚠️ Impossibile calcolare la completezza memoria: {e}")
            return None
        missing = sorted(comp.get("missing_categories", []))
        status = comp.get("status", "RED")
        if status == "GREEN":
            st.success(f"🟢 **Memoria PRONTA** · {comp.get('total_entries', 0)} blocchi · tutte le categorie chiave presenti.")
        elif status == "YELLOW":
            st.warning(
                f"🟡 **Memoria PARZIALE** · {comp.get('total_entries', 0)} blocchi. "
                f"Categorie mancanti: **{', '.join(missing) if missing else '-'}**. "
                "Carica i documenti mancanti per output piu' specifici."
            )
        else:
            st.error(
                "🔴 **Memoria INSUFFICIENTE.** "
                f"Carica almeno: **brand_book, regole_negative, esempi_copy**. "
                f"Mancano: **{', '.join(missing) if missing else '-'}**."
            )
        return comp

    render_memory_semaforo(client_id)
    st.markdown("")

    memory_summary = rag.get_memory_summary(client_id)
    reverse_mapping = {
        "brand_book": "📘 Brand Book / Linee Guida", "icp_personas": "👤 ICP / Personas & Pain/Gain",
        "gestione_obiezioni": "🛡️ Gestione Obiezioni", "esempi_copy": "✍️ Esempi di Copy Approvati",
        "istruzioni_creazione": "📝 Istruzioni Specifiche di Creazione", "note_call": "📞 Note da Call / Briefing",
        "regole_negative": "🚫 Regole Negative", "report_dati": "📊 Report / Dati Precedenti",
        "link_riferimento": "🔗 Link Asset, Competitor e Fonti", "sistema": "⚙️ Sistema",
        "regola_stile": "🧠 Regole Apprese (Opzione B)", "istruzioni_formato": "📝 Istruzioni di Formato", "errore": "❌ Errore DB"
    }
    has_data = any(key != "errore" for key in memory_summary)
    if not has_data:
        st.info("La memoria di questo cliente è vuota.")
    else:
        # FIX UX: Riepilogo rapido per dare sicurezza all'utente
        total_files = sum(len(data.get("files", [])) for data in memory_summary.values() if isinstance(data, dict))
        active_categories = len([k for k in memory_summary.keys() if k != "errore" and k != "sistema"])
        has_format_instructions = "istruzioni_formato" in memory_summary
        status_format = "✅ ATTIVE" if has_format_instructions else "⚠️ NON CONFIGURATE"

        st.info(f"📊 **Riepilogo:** {active_categories} categorie attive · {total_files} fonti totali · Istruzioni Formato: **{status_format}**")

        for doc_type, data in memory_summary.items():
            if doc_type == "errore":
                continue
            display_name = reverse_mapping.get(doc_type, f"📁 {doc_type}")
            with st.expander(f"**{display_name}** ({data.get('count', 0)} blocchi)"):
                for f in data.get("files", []):
                    col_f1, col_f2 = st.columns([4, 1])
                    with col_f1:
                        st.markdown(f"- 📄 `{f}`")
                    with col_f2:
                        if st.button("🗑️", key=f"del_{doc_type}_{f}"):
                            success, msg = rag.delete_specific_file(client_id, doc_type, f)
                            if success:
                                st.success(msg)
                                time.sleep(1)
                                st.rerun()
                if st.button(f"🗑️ ELIMINA TUTTA LA CATEGORIA", key=f"del_cat_{doc_type}", type="secondary"):
                    success, msg = rag.delete_category(client_id, doc_type)
                    if success:
                        st.success(msg)
                        time.sleep(1.5)
                        st.rerun()

    st.markdown("---")

    # --- CARICAMENTO FILE E LINK ---
    with st.expander("📎 Carica File, Testo o Link Web", expanded=False):
        col1, col2 = st.columns([2, 1])
        with col1:
            uploaded_files = st.file_uploader("📎 Carica file (PDF, DOCX, TXT, CSV)", type=["pdf", "docx", "txt", "csv"], accept_multiple_files=True)
            manual_text = st.text_area("Oppure incolla testo manuale:", height=150)
            urls_text = st.text_area("🌐 Oppure incolla URL da scansionare (uno per riga o separati da virgole)", height=100, placeholder="https://...")
        with col2:
            standard_categories = ["📘 Brand Book / Linee Guida", "👤 ICP / Personas & Pain/Gain", "🛡️ Gestione Obiezioni", "✍️ Esempi di Copy Approvati", "📝 Istruzioni Specifiche di Creazione", "📞 Note da Call / Briefing", "🚫 Regole Negative", "📊 Report / Dati Precedenti", "🔗 Link Asset, Competitor e Fonti", "➕ Scrivi una categoria personalizzata..."]
            selected_cat = st.selectbox("Scegli categoria", standard_categories, key="cat_select_file")
            custom_cat_valid = True
            if "➕" in selected_cat:
                _raw_custom = st.text_input("Nome categoria personalizzata", key="custom_cat_file")
                doc_type_file = _raw_custom.strip().lower().replace(" ", "_")
                if not doc_type_file:
                    st.error("⚠️ Inserisci un nome per la categoria personalizzata.")
                    custom_cat_valid = False
                else:
                    st.success(f"La categoria sara' salvata come: **`{doc_type_file}`**")
            else:
                mapping = {"📘 Brand Book / Linee Guida": "brand_book", "👤 ICP / Personas & Pain/Gain": "icp_personas", "🛡️ Gestione Obiezioni": "gestione_obiezioni", "✍️ Esempi di Copy Approvati": "esempi_copy", "📝 Istruzioni Specifiche di Creazione": "istruzioni_creazione", "📞 Note da Call / Briefing": "note_call", "🚫 Regole Negative": "regole_negative", "📊 Report / Dati Precedenti": "report_dati", "🔗 Link Asset, Competitor e Fonti": "link_riferimento"}
                doc_type_file = mapping.get(selected_cat, "generico")
                st.info(f"Salverai come: **`{doc_type_file}`**")

        if st.button("💾 Salva Contenuti nella Memoria", type="primary", disabled=not custom_cat_valid):
            debug_info = []
            if uploaded_files:
                for uploaded_file in uploaded_files:
                    try:
                        extracted = ""
                        uploaded_file.seek(0)
                        if uploaded_file.type in ["text/plain", "text/csv"]:
                            extracted = uploaded_file.read().decode("utf-8")
                        elif uploaded_file.type == "application/pdf":
                            reader = PyPDF2.PdfReader(uploaded_file)
                            extracted = "\n".join([page.extract_text() or "" for page in reader.pages])
                        elif uploaded_file.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                            doc = docx.Document(uploaded_file)
                            extracted = "\n".join([para.text for para in doc.paragraphs if para.text.strip()])
                        if len(extracted.strip()) > 0:
                            ok, msg = rag.add_document(client_id, extracted, doc_type_file, source_file=uploaded_file.name)
                            debug_info.append(msg)
                    except Exception as e:
                        debug_info.append(f"❌ {uploaded_file.name}: {str(e)}")
            if manual_text.strip():
                _mt = manual_text.strip()
                _spam_hits = len(re.findall(r'(?i)(clicca qui|vota per|compra ora|click here)', _mt))
                if len(_mt) < 50:
                    debug_info.append("WARNING: testo manuale troppo corto (min 50 caratteri), ignorato.")
                elif len(_mt) > 50000:
                    debug_info.append("WARNING: testo manuale troppo lungo (max 50.000 caratteri), ignorato.")
                elif _spam_hits >= 5:
                    debug_info.append("WARNING: testo manuale sembra spam (troppe CTA ripetute), ignorato.")
                else:
                    ok, msg = rag.add_document(client_id, _mt, doc_type_file, source_file="testo_manuale")
                    debug_info.append(msg)

            # Scansione URL batch
            if urls_text.strip():
                raw_urls = re.findall(r'https?://[^\s,;)]+|www\.[^\s,;)]+', urls_text)
                urls_list = list(set([u.strip('.,)>"\'') for u in raw_urls]))
                if urls_list:
                    debug_info.append(f"🌐 Avvio scansione di {len(urls_list)} URL...")
                    for url in urls_list:
                        ok, msg = rag.scrape_and_save_url(client_id, url, doc_type="link_riferimento")
                        debug_info.append(msg)

            if debug_info:
                st.markdown(f'<div class="debug-box">' + "\n".join(debug_info) + "</div>", unsafe_allow_html=True)
                time.sleep(1.5)
                st.rerun()

# ==========================================
# AGENTE 2: PED (CON JSON ROBUSTO)
# ==========================================
elif task_type == "📅 Piano Editoriale Completo":
    st.markdown('<div class="sub-header">Componi il tuo piano editoriale completo. Il sistema userà le istruzioni di formato specifiche per garantire qualità professionale.</div>', unsafe_allow_html=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        mese = st.text_input("📅 Periodo", "Gennaio 2025")
    with col2:
        obiettivo = st.selectbox("🎯 Obiettivo", ["Brand Awareness", "Lead Generation", "Lancio Prodotto", "Fidelizzazione", "Engagement"])
    with col3:
        durata = st.selectbox("⏱️ Durata", ["1 settimana", "2 settimane", "1 mese", "3 mesi"])

    tema = st.text_input("💡 Tema Centrale", "Es. Posizionamento come esperti")
    istruzioni_extra = st.text_area("📝 Note specifiche per questo piano", placeholder="Es. Promuovere l'evento del 15, evitare la parola 'sinergia'...")

    st.markdown("---")
    st.markdown("### 📱 1. Contenuti Social")
    canali_config = {}
    canali_disponibili = {"LinkedIn": "Post LinkedIn", "Instagram_Feed": "Post IG Feed", "Instagram_Reels": "Reel IG", "Instagram_Stories": "Story IG", "Facebook": "Post FB", "TikTok": "TikTok"}
    cols = st.columns(2)
    for idx, (canale, label) in enumerate(canali_disponibili.items()):
        with cols[idx % 2]:
            quant = st.slider(f"**{label}**", 0, 20, 0, key=f"slider_{canale}")
            if quant > 0:
                canali_config[canale] = quant

    st.markdown("---")
    st.markdown("### 🎙️ 2. Contenuti Long-Form")
    longform_config = {}
    longform_disponibili = {"Blog_Article": "Articoli Blog", "Podcast_Episode": "Episodi Podcast", "Newsletter": "Newsletter", "Video_YouTube": "Video YouTube"}
    cols_lf = st.columns(2)
    for idx, (tipo, label) in enumerate(longform_disponibili.items()):
        with cols_lf[idx % 2]:
            quant = st.slider(f"**{label}**", 0, 10, 0, key=f"slider_lf_{tipo}")
            if quant > 0:
                longform_config[tipo] = quant

    totale = sum(canali_config.values()) + sum(longform_config.values())

    # --- GATE COMPLETEZZA MEMORIA PRIMA DELLA GENERAZIONE ---
    try:
        ped_completeness = rag.get_memory_completeness(client_id)
    except Exception as e:
        ped_completeness = {"status": "RED", "missing_categories": set(), "total_entries": 0}
        st.warning(f"⚠️ Impossibile verificare la completezza memoria: {e}")
    ped_memory_status = ped_completeness.get("status", "RED")
    ped_missing = sorted(ped_completeness.get("missing_categories", []))

    if ped_memory_status == "GREEN":
        st.success("🟢 Memoria PRONTA: tutte le categorie chiave sono presenti.")
    elif ped_memory_status == "YELLOW":
        st.warning(
            f"🟡 Memoria PARZIALE: mancano **{', '.join(ped_missing) if ped_missing else '-'}**. "
            "Puoi generare ma l'output potrebbe non essere completamente specifico. "
            "Vai su **🧠 Carica e Gestisci Memoria** per aggiungere i documenti."
        )
    else:
        st.error(
            "🔴 Memoria INSUFFICIENTE: la generazione e' bloccata. "
            "Carica almeno **brand_book, regole_negative, esempi_copy** dalla sezione "
            f"**🧠 Carica e Gestisci Memoria**. Mancano: **{', '.join(ped_missing) if ped_missing else '-'}**."
        )

    if totale == 0:
        st.warning("⚠️ Configura almeno un contenuto per generare il piano.")
    else:
        st.success(f"🎯 Piano configurato: {totale} contenuti totali.")

        _gen_blocked = (ped_memory_status == "RED")
        if st.button(f"🚀 GENERA PIANO COMPLETO ({totale} contenuti)", type="primary", use_container_width=True, disabled=_gen_blocked):
            with st.spinner("Recupero contesto, istruzioni di formato e avvio generazione a batch..."):
                # Query ampie per il contesto PED (vedi note: con query ampie la
                # category guarantee resta soddisfatta). Usiamo il dict completo
                # per trasparenza grounding e il testo per il prompt.
                ctx_res = rag.get_client_context(client_id, "brand book, ICP, personas, pain, gain, obiezioni, tono di voce, link riferimento")
                context = ctx_res.get("context", "") or "Nessun contesto disponibile."
                if ctx_res.get("warning"):
                    context = context + "\n\n" + ctx_res["warning"]
                ctx_meta = ctx_res.get("metadata", {})
                format_instructions = rag.get_context_text(client_id, "istruzioni di formato, regole di scrittura, come scrivere", k=10)

                # Blacklist parole vietate (regole_negative) per validazione post-gen.
                try:
                    forbidden_words = rag.extract_constraints(client_id)
                except Exception:
                    forbidden_words = []

                request_list = []
                for ch, qty in canali_config.items():
                    request_list.extend([ch] * qty)
                for lf, qty in longform_config.items():
                    request_list.extend([lf] * qty)

                all_contents = []
                batch_size = 3
                total_batches = (len(request_list) + batch_size - 1) // batch_size

                progress_bar = st.progress(0)
                status_text = st.empty()

                for i in range(0, len(request_list), batch_size):
                    batch = request_list[i:i+batch_size]
                    current_batch_num = (i // batch_size) + 1
                    status_text.text(f"🔄 Generazione batch {current_batch_num}/{total_batches} ({len(batch)} contenuti)...")

                    batch_labels = []
                    for item in batch:
                        if item in canali_disponibili:
                            batch_labels.append(canali_disponibili[item])
                        elif item in longform_disponibili:
                            batch_labels.append(longform_disponibili[item])

                    prompt_pe = (
                        f"Sei un Senior Copywriter e Content Strategist. Genera ESATTAMENTE {len(batch)} contenuti in formato JSON STRICT.\n\n"
                        f"## CONTESTO CLIENTE (BASE ASSOLUTA):\n{context}\n\n"
                        f"## ISTRUZIONI DI FORMATO SPECIFICHE (DA SEGUIRE TASSATIVAMENTE):\n{format_instructions}\n\n"
                        f"## CONFIGURAZIONE PIANO:\nPeriodo: {mese} | Obiettivo: {obiettivo} | Tema Centrale: {tema} | Note: {istruzioni_extra}\n"
                        f"Tipologie da generare in questo batch: {', '.join(batch_labels)}\n\n"
                        f"## FORMATO OUTPUT JSON:\n[{{\"tipo\": \"...\", \"data\": \"YYYY-MM-DD\", \"titolo\": \"...\", \"hook\": \"...\", \"copy\": \"...\", \"cta\": \"...\", \"brief_visivo\": \"...\", \"hashtag_seo\": \"...\", \"note\": \"...\"}}]\n\n"
                        f"## VINCOLI OBBLIGATORI:\n"
                        f"1. Rispetta le 'Istruzioni di Formato Specifiche' per ogni tipologia.\n"
                        f"2. **ALLINEAMENTO TEMA**: Ogni contenuto deve ruotare ESPlicitamente attorno a: '{tema}'.\n"
                        f"3. **VIETATO**: Placeholder, 'Lorem ipsum', frasi generiche. Scrivi testi PRONTI ALLA PUBBLICAZIONE.\n"
                        f"4. **GROUNDING**: usa SOLO le informazioni del CONTESTO CLIENTE qui sopra (tono di voce, fatti, esempi). Se un dato non e' presente nel contesto, scrivi [INFORMAZIONE MANCANTE] invece di inventare.\n"
                        f"5. **PAROLE/FRASI VIETATE dal cliente** (non usarle MAI, in nessuna forma): {', '.join(forbidden_words) if forbidden_words else 'nessuna'}.\n"
                        f"6. Rispondi SOLO con il JSON valido, senza markdown o testo extra."
                    )

                    try:
                        response = rag.llm.invoke(prompt_pe).content

                        # FIX FULL STACK: Pulizia JSON robusta per gestire output LLM imperfetti
                        clean_json = response.strip()
                        clean_json = re.sub(r'^```(?:json)?\s*', '', clean_json)
                        clean_json = re.sub(r'\s*```$', '', clean_json)
                        clean_json = clean_json.strip()
                        # Estrae il blocco JSON anche se l'LLM aggiunge testo prima/dopo
                        _m = re.search(r'(\[.*\]|\{.*\})', clean_json, re.DOTALL)
                        if _m:
                            clean_json = _m.group(1)
                        clean_json = re.sub(r',\s*([\]}])', r'\1', clean_json)

                        data_list = json.loads(clean_json)
                        # L'LLM puo' restituire un singolo oggetto invece di un array:
                        # normalizziamo a lista e teniamo solo i contenuti validi (dict).
                        if isinstance(data_list, dict):
                            data_list = [data_list]
                        data_list = [d for d in data_list if isinstance(d, dict)]
                        all_contents.extend(data_list)
                    except Exception as e:
                        st.error(f"⚠️ Errore nel batch {current_batch_num}. Dettagli: {str(e)}")
                        with st.expander("Vedi output grezzo (per debug)"):
                            st.code(response)

                    progress_bar.progress(min(1.0, (i + batch_size) / len(request_list)))
                    time.sleep(1.5)

                status_text.text("✅ Generazione completata!")
                time.sleep(1)
                status_text.empty()
                progress_bar.empty()

                # Guardrail anti-invenzione: segnala se i testi violano le parole vietate del cliente
                if forbidden_words and all_contents:
                    _joined = " ".join(
                        f"{c.get('titolo','')} {c.get('hook','')} {c.get('copy','')} {c.get('cta','')}"
                        for c in all_contents
                    )
                    _is_clean, _violations = rag.validate_constraint_violation(_joined, forbidden_words)
                    if not _is_clean:
                        _bad = ", ".join(sorted(set(v.split(' (')[0] for v in _violations)))
                        st.warning(f"⚠️ Attenzione: il testo generato contiene PAROLE VIETATE dal cliente: **{_bad}**. Rivedi e correggi prima di pubblicare.")

                df = pd.DataFrame(all_contents)
                st.session_state['ped_full_plan'] = df
                st.success(f"✅ Piano completo generato con successo! ({len(df)} contenuti)")
                # Prova del grounding: mostra quali documenti del cliente sono stati usati
                _fonti_ped = ctx_res.get("metadata", {}).get("sources", [])
                if _fonti_ped:
                    st.caption("📚 Fonti di memoria usate per questo piano: " + ", ".join(_fonti_ped[:10]))
                else:
                    st.caption("📚 Nessuna memoria cliente trovata: il piano NON è ancorato a dati specifici di questo cliente.")
                st.data_editor(df, num_rows="dynamic", key="editable_df", height=600, use_container_width=True)

                # Export DOCX
                doc = docx.Document()
                doc.add_heading(f'Piano Editoriale: {client_id}', 0)
                doc.add_paragraph(f'Periodo: {mese} | Obiettivo: {obiettivo} | Durata: {durata}')
                doc.add_paragraph(f'Tema Centrale: {tema}')
                doc.add_paragraph('_' * 50)
                for idx, row in df.iterrows():
                    doc.add_heading(f"{idx + 1}. {row.get('titolo', 'Contenuto')}", level=1)
                    doc.add_paragraph(f"📌 Tipo: {row.get('tipo')} | 📅 Data: {row.get('data')}", style='Normal')
                    if row.get('hook'):
                        doc.add_paragraph(f"🎣 Hook: {row['hook']}")
                    if row.get('copy'):
                        doc.add_paragraph("📝 Copy:", style='Heading 3')
                        for p in str(row['copy']).split('\n'):
                            doc.add_paragraph(p.strip())
                    if row.get('cta'):
                        doc.add_paragraph(f"👉 CTA: {row['cta']}")
                    if row.get('brief_visivo'):
                        doc.add_paragraph(f"🎨 Brief: {row['brief_visivo']}")
                    doc.add_paragraph("__________________________________________________________________________________________")

                buf = io.BytesIO()
                doc.save(buf)
                buf.seek(0)
                st.download_button("📥 Scarica Piano in WORD (DOCX)", buf, f"PED_{client_id}_{mese.replace(' ','_')}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document", use_container_width=True)

    if 'ped_full_plan' in st.session_state:
        st.markdown("---")
        if st.button("💾 Salva e Insegna (Opzione B)", type="secondary"):
            with st.spinner("Analisi correzioni in corso..."):
                result = rag.save_and_teach(client_id, json.dumps(st.session_state['ped_full_plan'].to_dict(orient='records')), st.session_state['editable_df'].to_json(orient='records'))
                st.success(result)

# ==========================================
# AGENTE 3: REPORT ADS
# ==========================================
elif task_type == "📊 Report ADS Performance":
    st.markdown('<div class="sub-header">Genera report PDF professionale con analisi performance ADS</div>', unsafe_allow_html=True)
    st.info("💡 Scarica il report da Meta Ads Manager o Google Ads e caricalo qui (CSV o Excel).")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown("### 1. Dati Campagna")
        uploaded_report = st.file_uploader("📎 Carica Report (CSV o Excel)", type=["csv", "xlsx", "xls"], key="ads_upload")
        date_range = st.text_input("📅 Intervallo Date", "Es. 1-31 Ottobre 2024")
        obiettivo_campagna = st.selectbox("🎯 Obiettivo", ["Lead Generation", "Vendite/E-commerce", "Brand Awareness", "Traffico Sito"])
    with col2:
        st.markdown("### 2. Anteprima Contesto")
        memory_badge(client_id)
        context_preview = rag.get_context_text(client_id, "ICP, obiettivi strategici, pain gain")
        st.markdown(f'<div class="debug-box" style="max-height: 200px; overflow-y: auto; font-size: 0.75rem;">{context_preview[:500]}...</div>', unsafe_allow_html=True)

    if uploaded_report is not None:
        if st.button("🚀 Genera Report PDF", type="primary", use_container_width=True):
            with st.spinner("Analisi dati e generazione report in corso..."):
                try:
                    df_report = read_table(uploaded_report)
                    df_report.columns = [col.strip().lower().replace(' ', '_') for col in df_report.columns]
                    spend_col = next((c for c in df_report.columns if 'spes' in c or 'spend' in c or 'cost' in c or 'import' in c or 'invest' in c), None)
                    impr_col = next((c for c in df_report.columns if 'impression' in c or 'impres' in c), None)
                    click_col = next((c for c in df_report.columns if 'click' in c and 'ctr' not in c), None)
                    ctr_col = next((c for c in df_report.columns if 'ctr' in c), None)
                    cpa_col = next((c for c in df_report.columns if 'cpa' in c or 'cost_per' in c), None)
                    roas_col = next((c for c in df_report.columns if 'roas' in c or 'return' in c), None)
                    conv_col = next((c for c in df_report.columns if 'conv' in c or 'conversion' in c or 'risultat' in c), None)

                    # Conversione numerica robusta (gestisce "1.234,56", "EUR 10,50", "1,000")
                    total_spend = reporting.col_sum(df_report, spend_col)
                    total_impr = reporting.col_sum(df_report, impr_col)
                    total_click = reporting.col_sum(df_report, click_col)
                    total_conv = reporting.col_sum(df_report, conv_col)
                    avg_ctr = (total_click / total_impr * 100) if total_impr > 0 else 0
                    avg_cpa = (total_spend / total_conv) if total_conv > 0 else 0
                    avg_roas = reporting.col_mean(df_report, roas_col)

                    _missing = [k for k, v in {"Spesa": spend_col, "Impressioni": impr_col, "Click": click_col, "Conversioni": conv_col}.items() if not v]
                    if _missing:
                        st.warning("⚠️ Colonne non riconosciute nel file (messe a 0): " + ", ".join(_missing) + ". Controlla le intestazioni del report.")

                    csv_sample = df_report.head(20).to_string()
                    ctx = rag.get_client_context(client_id, "ICP, obiettivi strategici, tono di voce, pain gain")
                    metrics = [("Spesa Totale", f"EUR {total_spend:.2f}"), ("Impressioni", f"{total_impr:,.0f}"), ("Click Totali", f"{total_click:,.0f}"), ("CTR Medio", f"{avg_ctr:.2f}%"), ("Conversioni", f"{total_conv:,.0f}"), ("CPA Medio", f"EUR {avg_cpa:.2f}"), ("ROAS Medio", f"{avg_roas:.2f}x")]
                    metriche_str = " | ".join(f"{k}: {v}" for k, v in metrics)
                    prompt_analysis = reporting.build_standard_report_prompt("Report Performance ADS", client_id, date_range, ctx.get("context", ""), metriche_str, f"Obiettivo: {obiettivo_campagna}", csv_sample)
                    ai_analysis = rag.llm.invoke(prompt_analysis).content
                    fonti = ctx.get("metadata", {}).get("sources", [])
                    pdf_bytes = reporting.build_standard_report_pdf("Report Performance ADS", client_id, date_range, metrics, ai_analysis, fonti)

                    st.success("✅ Report generato con successo!")
                    if fonti:
                        st.caption("📚 Fonti di memoria usate: " + ", ".join(fonti[:8]))
                    else:
                        st.caption("📚 Nessuna memoria cliente trovata: report basato solo sui dati caricati.")
                    st.markdown("### 📈 Anteprima Analisi")
                    st.markdown(f'<div class="insight-box">{ai_analysis}</div>', unsafe_allow_html=True)
                    slides_html = reporting.build_report_slides_html("Report Performance ADS", client_id, date_range, metrics, ai_analysis, fonti)
                    st.download_button(label="🖥️ Scarica Slide (HTML)", data=slides_html, file_name=f"Slide_ADS_{client_id}_{date_range.replace(' ', '_')}.html", mime="text/html", type="primary", use_container_width=True)
                    st.caption("Apri il file nel browser → naviga con le frecce. Per il PDF: Stampa (Ctrl/Cmd+P) → Salva come PDF, attivando 'Grafica di sfondo'.")
                    st.download_button(label="📄 (alternativa) Scarica PDF documento", data=pdf_bytes, file_name=f"Report_ADS_{client_id}_{date_range.replace(' ', '_')}.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"❌ Errore: {str(e)}")

# ==========================================
# AGENTE 4: REPORT SOCIAL
# ==========================================
elif task_type == "📱 Report Social Organico":
    st.markdown('<div class="sub-header">Genera report PDF con analisi performance organica social</div>', unsafe_allow_html=True)
    st.info("💡 Carica un file (CSV o Excel) con i dati dei post social.")
    col1, col2 = st.columns([1, 2])
    with col1:
        st.markdown("### 1. Dati Social")
        uploaded_social = st.file_uploader("📎 Carica file Post Social (CSV o Excel)", type=["csv", "xlsx", "xls"], key="social_upload")
        date_range_social = st.text_input("📅 Intervallo Date", "Es. Ottobre 2024")
        piattaforme = st.multiselect("📱 Piattaforme Incluse", ["Instagram", "Facebook", "LinkedIn", "TikTok", "Twitter"], default=["Instagram", "LinkedIn"])
    with col2:
        st.markdown("### 2. Contesto Strategico")
        memory_badge(client_id)
        context_preview = rag.get_context_text(client_id, "ICP, tono di voce, obiettivi social")
        st.markdown(f'<div class="debug-box" style="max-height: 200px; overflow-y: auto; font-size: 0.75rem;">{context_preview[:500]}...</div>', unsafe_allow_html=True)

    if uploaded_social is not None:
        if st.button("🚀 Genera Report Social PDF", type="primary", use_container_width=True):
            with st.spinner("Analisi contenuti e generazione report..."):
                try:
                    df_social = read_table(uploaded_social)
                    df_social.columns = [col.strip().lower().replace(' ', '_') for col in df_social.columns]
                    likes_col = next((c for c in df_social.columns if 'like' in c or 'reaction' in c or 'mi piace' in c), None)
                    comments_col = next((c for c in df_social.columns if 'comment' in c or 'commenti' in c), None)
                    shares_col = next((c for c in df_social.columns if 'share' in c or 'condiv' in c), None)
                    reach_col = next((c for c in df_social.columns if 'reach' in c or 'portata' in c or 'copert' in c), None)
                    engagement_col = next((c for c in df_social.columns if 'engagement' in c or 'eng_rate' in c or 'interazion' in c), None)

                    # Conversione numerica robusta (export reali con separatori/simboli)
                    total_posts = len(df_social)
                    total_likes = reporting.col_sum(df_social, likes_col)
                    total_comments = reporting.col_sum(df_social, comments_col)
                    total_shares = reporting.col_sum(df_social, shares_col)
                    total_reach = reporting.col_sum(df_social, reach_col)
                    avg_engagement = reporting.col_mean(df_social, engagement_col)

                    _missing = [k for k, v in {"Like": likes_col, "Commenti": comments_col, "Reach": reach_col, "Engagement": engagement_col}.items() if not v]
                    if _missing:
                        st.warning("⚠️ Colonne non riconosciute nel file (messe a 0): " + ", ".join(_missing) + ". Controlla le intestazioni del report.")

                    social_sample = df_social.head(20).to_string()
                    ctx = rag.get_client_context(client_id, "ICP, tono di voce, obiettivi social, pain gain")
                    metrics_social = [("Post Totali", f"{total_posts}"), ("Like Totali", f"{total_likes:,.0f}"), ("Commenti", f"{total_comments:,.0f}"), ("Condivisioni", f"{total_shares:,.0f}"), ("Reach Totale", f"{total_reach:,.0f}"), ("Engagement Rate Medio", f"{avg_engagement:.2f}%")]
                    metriche_str = " | ".join(f"{k}: {v}" for k, v in metrics_social)
                    prompt_social = reporting.build_standard_report_prompt("Report Social Organico", client_id, date_range_social, ctx.get("context", ""), metriche_str, f"Piattaforme: {', '.join(piattaforme)}", social_sample)
                    ai_analysis_social = rag.llm.invoke(prompt_social).content
                    fonti = ctx.get("metadata", {}).get("sources", [])
                    pdf_bytes = reporting.build_standard_report_pdf("Report Social Organico", client_id, date_range_social, metrics_social, ai_analysis_social, fonti)

                    st.success("✅ Report Social generato con successo!")
                    if fonti:
                        st.caption("📚 Fonti di memoria usate: " + ", ".join(fonti[:8]))
                    else:
                        st.caption("📚 Nessuna memoria cliente trovata: report basato solo sui dati caricati.")
                    st.markdown("### 📈 Anteprima Analisi")
                    st.markdown(f'<div class="insight-box">{ai_analysis_social}</div>', unsafe_allow_html=True)
                    slides_html = reporting.build_report_slides_html("Report Social Organico", client_id, date_range_social, metrics_social, ai_analysis_social, fonti)
                    st.download_button(label="🖥️ Scarica Slide (HTML)", data=slides_html, file_name=f"Slide_Social_{client_id}_{date_range_social.replace(' ', '_')}.html", mime="text/html", type="primary", use_container_width=True)
                    st.caption("Apri il file nel browser → naviga con le frecce. Per il PDF: Stampa (Ctrl/Cmd+P) → Salva come PDF, attivando 'Grafica di sfondo'.")
                    st.download_button(label="📄 (alternativa) Scarica PDF documento", data=pdf_bytes, file_name=f"Report_Social_{client_id}_{date_range_social.replace(' ', '_')}.pdf", mime="application/pdf")
                except Exception as e:
                    st.error(f"❌ Errore: {str(e)}")

# ==========================================
# AGENTE 5: COMPETITOR
# ==========================================
elif task_type == "🔍 Analisi Competitor / Trend":
    st.markdown('<div class="sub-header">Ricerca sul web trend o competitor</div>', unsafe_allow_html=True)
    query_ricerca = st.text_input("🔍 Cosa cercare? (es. 'trend marketing B2B gennaio 2025')")
    if st.button("🌐 Avvia Ricerca Web", type="primary"):
        if query_ricerca:
            with st.spinner("Ricerca in corso..."):
                search_results = rag.web_search(query_ricerca, num_results=5)
                if "Errore" in search_results or "⚠️" in search_results:
                    st.warning(search_results)
                else:
                    st.markdown("### 📊 Risultati")
                    st.markdown(search_results)
                    with st.spinner("Sintesi insight..."):
                        context = rag.get_context_text(client_id, "obiettivi strategici, ICP, pain gain, link competitor")
                        prompt_sintesi = f"Sei un Brand Strategist. Ricerca:\n{search_results}\nCliente: '{client_id}'. Contesto: {context}\nSintetizza in 3 insight pratici."
                        st.info(rag.llm.invoke(prompt_sintesi).content)

# ==========================================
# AGENTE 6: ONBOARDING AUTOMATICO NUOVO CLIENTE
# ==========================================
elif task_type == "🚀 Onboarding Nuovo Cliente":
    st.markdown('<div class="sub-header">Genera la memoria di un nuovo cliente partendo da sito, social e asset</div>', unsafe_allow_html=True)
    st.info("Incolla il sito e i profili social del cliente: l'AI li analizza e propone brand, tono di voce, ICP, esempi di copy e regole. Tu controlli, modifichi e salvi. ℹ️ Alcuni social (Instagram/LinkedIn) sono protetti e danno poco testo: in quel caso incolla anche bio/brochure/copy nello spazio note.")

    urls_in = st.text_area("🌐 URL del cliente (sito, Instagram, LinkedIn, Facebook) — uno per riga", height=120, placeholder="https://www.cliente.it\nhttps://instagram.com/cliente")
    extra = st.text_area("📝 Testi/asset incollati a mano (bio, brochure, copy esistenti) — opzionale ma consigliato", height=140)

    if st.button("🔎 Analizza fonti e genera profilo", type="primary", use_container_width=True):
        urls = re.findall(r'https?://[^\s,;]+', urls_in)
        material = ""
        if urls:
            with st.spinner(f"Scansione di {len(urls)} URL..."):
                scraped = onboarding.scrape_urls(urls)
            for u, t, stato in scraped:
                if t:
                    st.success(f"✅ {u} — {len(t)} caratteri estratti")
                    material += f"\n\n[FONTE: {u}]\n{t}"
                else:
                    st.warning(f"⚠️ {u} — {stato}")
        if extra.strip():
            material += f"\n\n[NOTE/ASSET MANUALI]\n{extra.strip()}"

        if len(material.strip()) < 100:
            st.error("Troppo poco materiale: incolla almeno qualche testo a mano per generare un profilo sensato.")
        else:
            with st.spinner("L'AI sta costruendo il profilo del cliente..."):
                st.session_state['onboarding_profile'] = onboarding.generate_profile(client_id, material, extra)
            st.success("✅ Profilo generato! Controllalo e modificalo qui sotto, poi salva.")

    if 'onboarding_profile' in st.session_state:
        st.markdown("---")
        st.markdown("### 📋 Profilo proposto (modificabile prima del salvataggio)")
        prof = st.session_state['onboarding_profile']
        edited = {}
        for key in onboarding.PROFILE_KEYS:
            edited[key] = st.text_area(onboarding.PROFILE_LABELS[key], value=prof.get(key, ""), height=130, key=f"ob_{key}")
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("💾 Salva tutto nella memoria", type="primary", use_container_width=True):
                salvate, dettagli = onboarding.save_profile(client_id, edited)
                if salvate:
                    st.success(f"✅ Salvati {salvate} blocchi nella memoria di '{client_id}'.")
                else:
                    st.warning("Niente salvato: compila almeno una sezione (min. 50 caratteri).")
                with st.expander("Dettaglio salvataggio"):
                    st.write("\n".join(dettagli))
                st.session_state.pop('onboarding_profile', None)
        with col_b:
            if st.button("🗑️ Scarta profilo", use_container_width=True):
                st.session_state.pop('onboarding_profile', None)
                st.rerun()
