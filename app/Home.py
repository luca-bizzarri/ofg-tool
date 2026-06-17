import os
import re
import sys
import time

import streamlit as st
import pandas as pd
import PyPDF2
import docx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import rag_engine as rag
from core import clients, onboarding, ped, creative, slides

_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "Logo_no payoff_nero.png")

st.set_page_config(page_title="OFG Tool — PED", layout="wide", page_icon="🚀")
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Raleway:wght@300;400;600;800;900&display=swap');
    html, body, [class*="css"], .stApp, button, input, textarea, select { font-family: 'Raleway', sans-serif !important; }
    .main-header {font-size: 2.1rem; font-weight: 900; color: #111; margin-bottom: 0.3rem; border-bottom: 5px solid #ffd400; display: inline-block; padding-bottom: 4px;}
    .sub-header {font-size: 1.0rem; color: #555; margin-bottom: 1.2rem;}
    .out-box {background-color: #fffdf0; border-left: 5px solid #ffd400; padding: 18px; border-radius: 6px; margin-bottom: 15px; white-space: pre-wrap;}
    .stButton>button[kind="primary"] {background-color: #111; border: 2px solid #111;}
    .stButton>button[kind="primary"]:hover {background-color: #ffd400; color: #111; border-color: #ffd400;}
    </style>
""", unsafe_allow_html=True)


def check_password():
    try:
        expected = st.secrets.get("APP_PASSWORD", "")
    except Exception:
        expected = ""
    if not expected:
        return True
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


def extract_uploaded(uploaded_file) -> str:
    """Estrae il testo da un file caricato (PDF/DOCX/TXT)."""
    name = (uploaded_file.name or "").lower()
    try:
        uploaded_file.seek(0)
        if name.endswith(".pdf"):
            reader = PyPDF2.PdfReader(uploaded_file)
            return "\n".join((p.extract_text() or "") for p in reader.pages)
        if name.endswith(".docx"):
            d = docx.Document(uploaded_file)
            return "\n".join(p.text for p in d.paragraphs if p.text.strip())
        return uploaded_file.read().decode("utf-8", errors="ignore")
    except Exception:
        return ""


if not check_password():
    st.stop()

# ==========================================================
# SIDEBAR — selezione cliente
# ==========================================================
if os.path.exists(_LOGO):
    st.sidebar.image(_LOGO, use_container_width=True)
st.sidebar.title("OFG Tool — PED")

all_clients = rag.get_all_clients()
sel = st.sidebar.selectbox("👤 Cliente", ["➕ NUOVO CLIENTE..."] + all_clients, key="client_sel")
client_id = ""

if sel == "➕ NUOVO CLIENTE...":
    new_id = st.sidebar.text_input("ID nuovo cliente").strip().replace(" ", "_")
    if st.sidebar.button("✅ Crea cliente", type="primary", use_container_width=True):
        if not new_id:
            st.sidebar.error("Inserisci un ID.")
        elif new_id in all_clients:
            st.sidebar.warning("Esiste già.")
        else:
            rag.register_client(new_id)
            rag.add_document(new_id, f"Cliente {new_id} inizializzato.", "sistema", "sistema")
            clients.save_profile(new_id, clients.get_profile(new_id))
            st.sidebar.success(f"Creato '{new_id}'. Vai su Onboarding.")
            time.sleep(1)
            st.rerun()
else:
    client_id = sel
    if st.session_state.get("_active") != client_id:
        for k in ["onb_profile", "ped_content", "ped_calendar", "idea_out", "adv_out"]:
            st.session_state.pop(k, None)
        st.session_state["_active"] = client_id
    prof = clients.get_profile(client_id)
    st.sidebar.success(f"🟢 {client_id}")
    st.sidebar.caption(f"Lingue: {', '.join(prof['languages'])} · Rubriche: {len(prof['rubriche'])}")
    with st.sidebar.expander("🗑️ Elimina cliente"):
        if st.text_input(f"Scrivi {client_id} per confermare", key="del_confirm").strip() == client_id:
            if st.button("Elimina definitivamente", type="secondary"):
                rag.delete_client(client_id)
                st.success("Eliminato.")
                time.sleep(1)
                st.rerun()

if not client_id:
    st.markdown('<div class="main-header">OFG Tool — Piano Editoriale</div>', unsafe_allow_html=True)
    st.info("👈 Crea o seleziona un cliente per iniziare. Per un cliente nuovo, parti dall'**Onboarding**.")
    st.stop()

profile = clients.get_profile(client_id)
rubriche = profile.get("rubriche", [])
languages = profile.get("languages", ["IT"])
channels = profile.get("channels") or clients.CHANNELS[:2]

st.markdown(f'<div class="main-header">{client_id}</div>', unsafe_allow_html=True)
area = st.radio("Area", ["🚀 Onboarding", "🗂️ Scheda & Apprendimento", "💡 Ideazione", "📅 PED", "📣 ADV", "🖼️ Slide"], horizontal=True)
st.markdown("---")


# ==========================================================
# 🚀 ONBOARDING
# ==========================================================
if area == "🚀 Onboarding":
    st.markdown('<div class="sub-header">Costruisci la scheda del cliente da sito, social e asset (con scansione delle sotto-pagine)</div>', unsafe_allow_html=True)
    urls_in = st.text_area("🌐 URL (sito, social) — uno per riga", height=110, placeholder="https://www.cliente.it\nhttps://instagram.com/cliente")
    c1, c2 = st.columns(2)
    max_pages = c1.slider("Max pagine da scansionare (incluse sotto-pagine)", 3, 30, 12)
    lang_pre = c2.multiselect("Lingue del copy", ["IT", "EN"], default=languages)
    extra = st.text_area("📝 Incolla qui bio, caption approvate, brochure, copy esistenti (consigliato)", height=160)

    if st.button("🔎 Scansiona e genera scheda", type="primary", use_container_width=True):
        urls = re.findall(r'https?://[^\s,;]+', urls_in)
        material = ""
        if urls:
            with st.spinner(f"Scansione di max {max_pages} pagine (sito + sotto-pagine)..."):
                pages = onboarding.crawl_urls(urls, max_pages=max_pages)
            ok_n = sum(1 for _, t, _ in pages if t)
            st.success(f"✅ Scansionate {len(pages)} pagine, {ok_n} con testo utile.")
            with st.expander("Dettaglio pagine"):
                for u, t, s in pages:
                    st.write(f"{'✅' if t else '⚠️'} {u} — {s}")
                    if t:
                        material += f"\n\n[FONTE: {u}]\n{t}"
        if extra.strip():
            material += f"\n\n[NOTE/ASSET MANUALI]\n{extra.strip()}"
        if len(material.strip()) < 100:
            st.error("Troppo poco materiale: incolla testi a mano.")
        else:
            with st.spinner("L'AI sta costruendo la scheda (brand, TOV, ICP, rubriche)..."):
                p = onboarding.generate_profile(client_id, material, extra)
                if lang_pre:
                    p["languages"] = lang_pre
                st.session_state["onb_profile"] = p
            st.success("✅ Scheda proposta! Controllala e salva qui sotto.")

    if "onb_profile" in st.session_state:
        p = st.session_state["onb_profile"]
        st.markdown("### 📋 Scheda proposta (modificabile)")
        ed = {}
        for k in onboarding.TEXT_KEYS:
            ed[k] = st.text_area(onboarding.TEXT_LABELS[k], value=p.get(k, ""), height=120, key=f"onb_{k}")
        ed["languages"] = st.multiselect("Lingue", ["IT", "EN"], default=p.get("languages", ["IT"]), key="onb_lang")
        st.markdown("**Rubriche suggerite** (modificabili)")
        rub_df = pd.DataFrame(p.get("rubriche", []) or [clients.new_rubrica()])
        ed_rub = st.data_editor(rub_df, num_rows="dynamic", use_container_width=True, key="onb_rub")
        if st.button("💾 Salva scheda cliente", type="primary"):
            ed["rubriche"] = [r for r in ed_rub.to_dict(orient="records") if str(r.get("nome", "")).strip()]
            n, det = onboarding.save_profile(client_id, ed)
            st.success(f"✅ Salvati {n} blocchi in memoria + scheda aggiornata.")
            with st.expander("Dettaglio"):
                st.write("\n".join(det))
            st.session_state.pop("onb_profile", None)


# ==========================================================
# 🗂️ SCHEDA & APPRENDIMENTO
# ==========================================================
elif area == "🗂️ Scheda & Apprendimento":
    st.markdown('<div class="sub-header">Gestisci lingue, rubriche, memoria e insegna lo stile dai copy approvati</div>', unsafe_allow_html=True)

    st.markdown("### 🌐 Lingue e canali")
    cc1, cc2 = st.columns(2)
    langs = cc1.multiselect("Lingue del copy", ["IT", "EN"], default=languages)
    chans = cc2.multiselect("Canali abituali", clients.CHANNELS, default=channels)
    if st.button("💾 Salva lingue/canali"):
        profile["languages"] = langs or ["IT"]
        profile["channels"] = chans
        clients.save_profile(client_id, profile)
        st.success("Salvato.")
        st.rerun()

    st.markdown("---")
    st.markdown("### 🗂️ Rubriche del cliente")
    st.caption("Sono i format editoriali ricorrenti. Guidano la generazione del PED.")
    rub_df = pd.DataFrame(rubriche if rubriche else [clients.new_rubrica()])
    ed_rub = st.data_editor(rub_df, num_rows="dynamic", use_container_width=True, key="card_rub",
                            column_config={"tipologia": st.column_config.SelectboxColumn(options=["post", "carousel", "reel", "stories"])})
    if st.button("💾 Salva rubriche", type="primary"):
        new_rub = [r for r in ed_rub.to_dict(orient="records") if str(r.get("nome", "")).strip()]
        clients.upsert_rubriche(client_id, new_rub)
        st.success(f"Salvate {len(new_rub)} rubriche.")
        st.rerun()

    st.markdown("---")
    st.markdown("### 🎓 Apprendimento dai copy approvati")
    st.caption("Incolla un copy APPROVATO dal cliente (ed eventualmente quello che avevi generato tu): l'AI estrae le regole di stile e le salva, migliorando i contenuti futuri.")
    la1, la2 = st.columns(2)
    ai_copy = la1.text_area("📝 Copy generato dall'AI (opzionale)", height=160)
    appr_copy = la2.text_area("✅ Copy approvato finale", height=160)
    if st.button("🎓 Impara dallo stile", type="primary"):
        if len(appr_copy.strip()) < 30:
            st.warning("Incolla almeno il copy approvato.")
        else:
            with st.spinner("Estrazione regole di stile..."):
                res = rag.save_and_teach(client_id, ai_copy.strip() or "(nessun originale)", appr_copy.strip())
                rag.add_document(client_id, appr_copy.strip(), "esempi_copy", "copy_approvato")
            st.success("✅ Imparato e salvato come regola di stile + esempio approvato.")
            st.info(res)

    st.markdown("---")
    st.markdown("### 📂 Memoria attuale")
    st.caption("Vedi e modifica voce per voce cosa è salvato, ed aggiungi file/testi tuoi a ogni categoria.")
    STD_CATS = {
        "📘 Brand Book": "brand_book", "🗣️ Tono di voce / Istruzioni": "istruzioni_creazione",
        "👤 ICP / Personas": "icp_personas", "✍️ Esempi di copy": "esempi_copy",
        "🚫 Regole negative": "regole_negative", "📞 Note / Briefing": "note_call",
        "🔗 Link / Fonti": "link_riferimento",
    }
    summ = rag.get_memory_summary(client_id)
    for dt, data in summ.items():
        if dt == "errore":
            continue
        with st.expander(f"📁 {dt} — {data.get('count', 0)} blocchi · {len(data.get('files', []))} fonti"):
            for f in data.get("files", []):
                st.markdown(f"**📄 {f}**")
                cur = rag.get_document_text(client_id, dt, f)
                new_txt = st.text_area("contenuto", value=cur, height=150, key=f"edit_{dt}_{f}", label_visibility="collapsed")
                bc1, bc2, _ = st.columns([1, 1, 3])
                if bc1.button("💾 Salva modifiche", key=f"save_{dt}_{f}"):
                    rag.replace_document(client_id, dt, f, new_txt)
                    st.success("Salvato.")
                    time.sleep(0.6)
                    st.rerun()
                if bc2.button("🗑️ Elimina", key=f"del_{dt}_{f}"):
                    rag.delete_specific_file(client_id, dt, f)
                    st.rerun()
                st.divider()
            st.markdown("**➕ Aggiungi a questa categoria**")
            up = st.file_uploader("File (PDF/DOCX/TXT)", type=["pdf", "docx", "txt"], accept_multiple_files=True, key=f"up_{dt}")
            man = st.text_area("Oppure incolla testo", height=90, key=f"man_{dt}")
            if st.button("Aggiungi", key=f"add_{dt}"):
                added = 0
                for uf in (up or []):
                    txt = extract_uploaded(uf)
                    if txt.strip():
                        ok, _ = rag.add_document(client_id, txt, dt, source_file=uf.name)
                        added += 1 if ok else 0
                if man.strip():
                    ok, _ = rag.add_document(client_id, man.strip(), dt, source_file="testo_manuale")
                    added += 1 if ok else 0
                st.success(f"Aggiunti {added} elementi a '{dt}'.")
                time.sleep(0.8)
                st.rerun()

    with st.expander("➕ Aggiungi una NUOVA voce (anche in una categoria non ancora presente)"):
        cat_label = st.selectbox("Categoria", list(STD_CATS.keys()))
        up2 = st.file_uploader("File (PDF/DOCX/TXT)", type=["pdf", "docx", "txt"], accept_multiple_files=True, key="up_new")
        man2 = st.text_area("Oppure incolla testo", height=100, key="man_new")
        if st.button("Aggiungi alla memoria", type="primary", key="add_new"):
            dt2 = STD_CATS[cat_label]
            added = 0
            for uf in (up2 or []):
                txt = extract_uploaded(uf)
                if txt.strip():
                    ok, _ = rag.add_document(client_id, txt, dt2, source_file=uf.name)
                    added += 1 if ok else 0
            if man2.strip():
                ok, _ = rag.add_document(client_id, man2.strip(), dt2, source_file="testo_manuale")
                added += 1 if ok else 0
            st.success(f"Aggiunti {added} elementi a '{cat_label}'.")
            time.sleep(0.8)
            st.rerun()


# ==========================================================
# 💡 IDEAZIONE
# ==========================================================
elif area == "💡 Ideazione":
    st.markdown('<div class="sub-header">Genera più direzioni creative diverse, ancorate al brand</div>', unsafe_allow_html=True)
    i1, i2 = st.columns(2)
    tip = i1.selectbox("Tipologia di idee", creative.IDEA_TYPES)
    obj = i2.selectbox("Obiettivo", clients.OBJECTIVES)
    plats = st.multiselect("Piattaforme", clients.CHANNELS, default=channels)
    note = st.text_area("Note / brief aggiuntivo", height=90)
    if st.button("💡 Genera idee", type="primary", use_container_width=True):
        with st.spinner("Generazione direzioni creative..."):
            out, fonti = creative.generate_ideazione(client_id, tip, obj, plats, note)
            st.session_state["idea_out"] = (out, fonti)
    if "idea_out" in st.session_state:
        out, fonti = st.session_state["idea_out"]
        st.markdown(f'<div class="out-box">{out}</div>', unsafe_allow_html=True)
        if fonti:
            st.caption("📚 Fonti memoria: " + ", ".join(fonti[:6]))


# ==========================================================
# 📅 PED
# ==========================================================
elif area == "📅 PED":
    if not rubriche:
        st.warning("⚠️ Questo cliente non ha rubriche. Vai su **Onboarding** o **Scheda & Apprendimento** per definirle: guidano la generazione.")
    tab_single, tab_cal = st.tabs(["✍️ Contenuto singolo", "📅 Calendario mensile (Excel)"])

    with tab_single:
        rub_names = [r["nome"] for r in rubriche] or ["(rubrica libera)"]
        s1, s2, s3 = st.columns(3)
        rub_sel = s1.selectbox("Rubrica", rub_names)
        tipologia = s2.selectbox("Tipologia contenuto", ["post", "carousel", "reel", "stories"])
        obj = s3.selectbox("Obiettivo", clients.OBJECTIVES, key="ped_obj")
        plats = st.multiselect("Piattaforme", clients.CHANNELS, default=channels, key="ped_plat")
        prodotto = st.text_input("Prodotto / tema centrale")
        needs = st.multiselect("Di cosa hai bisogno", ped.NEEDS.get(tipologia, []), default=ped.NEEDS.get(tipologia, []))
        extra = st.text_area("Note / brief dettagliato", height=90, key="ped_extra")
        if st.button("✍️ Genera contenuto", type="primary", use_container_width=True):
            rub_obj = clients.rubrica_by_name(client_id, rub_sel) or clients.new_rubrica(nome=rub_sel)
            with st.spinner("Generazione contenuto..."):
                out, fonti = ped.generate_content(client_id, rub_obj, tipologia, obj, plats, prodotto, needs, languages, extra)
                st.session_state["ped_content"] = (out, fonti)
        if "ped_content" in st.session_state:
            out, fonti = st.session_state["ped_content"]
            st.markdown(f'<div class="out-box">{out}</div>', unsafe_allow_html=True)
            if fonti:
                st.caption("📚 Fonti memoria: " + ", ".join(fonti[:6]))

    with tab_cal:
        rub_names = [r["nome"] for r in rubriche]
        attive = st.multiselect("Rubriche da attivare nel piano", rub_names, default=rub_names)
        cc1, cc2, cc3 = st.columns(3)
        mese = cc1.selectbox("Mese", ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"])
        anno = cc2.text_input("Anno", "2026")
        n_cont = cc3.slider("Numero contenuti", 4, 40, 12)
        channel = st.selectbox("Canale principale", clients.CHANNELS, index=0)
        cal_extra = st.text_area("Note per il piano", height=80, key="cal_extra")
        if st.button("📅 Genera calendario", type="primary", use_container_width=True):
            if not attive:
                st.warning("Seleziona almeno una rubrica.")
            else:
                rub_objs = [clients.rubrica_by_name(client_id, n) or clients.new_rubrica(nome=n) for n in attive]
                with st.spinner(f"Generazione di {n_cont} contenuti..."):
                    rows, fonti = ped.generate_calendar(client_id, rub_objs, mese, anno, n_cont, channel, languages, cal_extra)
                    st.session_state["ped_calendar"] = (rows, mese, anno)
        if "ped_calendar" in st.session_state:
            rows, m, a = st.session_state["ped_calendar"]
            st.success(f"✅ {len(rows)} contenuti generati.")
            st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)
            xlsx = ped.export_excel(rows, m, languages)
            st.download_button("📥 Scarica PED in Excel", data=xlsx,
                               file_name=f"PED_{client_id}_{m}_{a}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               type="primary", use_container_width=True)


# ==========================================================
# 📣 ADV
# ==========================================================
elif area == "📣 ADV":
    st.markdown('<div class="sub-header">Sviluppa una campagna ADV completa</div>', unsafe_allow_html=True)
    a1, a2 = st.columns(2)
    nome_promo = a1.text_input("Nome promo")
    obj = a2.selectbox("Obiettivo promo", clients.OBJECTIVES, key="adv_obj")
    a3, a4 = st.columns(2)
    timing = a3.text_input("Timing (es. 1-15 Marzo)")
    scont = a4.text_input("Scontistica (es. -20%)")
    plats = st.multiselect("Piattaforme", clients.CHANNELS, default=channels, key="adv_plat")
    messaggi = st.text_area("Concetti / messaggi chiave da veicolare", height=100)
    concept = st.text_area("Concept ADV già definito (opzionale)", height=70)
    email_si = st.checkbox("Serve materiale email marketing a supporto")
    if st.button("📣 Genera campagna", type="primary", use_container_width=True):
        with st.spinner("Sviluppo campagna ADV..."):
            out, fonti = creative.generate_adv(client_id, nome_promo, obj, timing, plats, scont, messaggi, email_si, concept)
            st.session_state["adv_out"] = (out, fonti)
    if "adv_out" in st.session_state:
        out, fonti = st.session_state["adv_out"]
        st.markdown(f'<div class="out-box">{out}</div>', unsafe_allow_html=True)
        if fonti:
            st.caption("📚 Fonti memoria: " + ", ".join(fonti[:6]))


# ==========================================================
# 🖼️ SLIDE — genera il markdown OFG per lo Slide Builder
# ==========================================================
if area == "🖼️ Slide":
    st.markdown('<div class="sub-header">Genera le slide OFG da un brief e/o dal testo che incolli — poi le apri nello Slide Builder</div>', unsafe_allow_html=True)
    sb1, sb2 = st.columns(2)
    sl_brief = sb1.text_area("🎯 Brief / obiettivo", height=120, placeholder="Es: report di performance H1 2026 per questo cliente, 8 slide, tono professionale.")
    sl_text = sb2.text_area("📋 Testo da strutturare (incolla qui)", height=120, placeholder="Incolla contenuti da PPT, Word, email, appunti…")
    sl_max = st.slider("Numero massimo di slide", 4, 20, 10)
    use_brand = st.checkbox(f"Usa la memoria di brand del cliente «{client_id}»", value=bool(client_id))

    if st.button("✨ Genera slide", type="primary", use_container_width=True):
        if not sl_brief.strip() and not sl_text.strip():
            st.error("Inserisci un brief oppure incolla del testo.")
        else:
            with st.spinner("L'AI sta componendo le slide…"):
                try:
                    res = slides.compose(
                        brief=sl_brief,
                        text=sl_text,
                        client_id=(client_id if use_brand else None),
                        max_slides=sl_max,
                    )
                    st.session_state["slides_md"] = res["markdown"]
                except Exception as e:
                    st.error(f"Generazione non riuscita: {e}")

    if st.session_state.get("slides_md"):
        md = st.session_state["slides_md"]
        n = len([b for b in re.split(r'\n\s*-{3,}\s*\n', md) if b.strip()])
        st.success(f"✅ Generate {n} slide. Copia il markdown qui sotto e incollalo nello Slide Builder (pannello sorgente, oppure Importa → Markdown).")
        st.code(md, language="markdown")
        st.download_button("⬇️ Scarica .md", data=md, file_name="presentazione-ofg.md", mime="text/markdown")
        st.markdown("[↗️ Apri lo Slide Builder](https://luca-bizzarri.github.io/ofg-slide-builder/)")
        st.caption("Le foto si aggiungono direttamente nello Slide Builder (galleria → slide).")
