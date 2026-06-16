# OFG Tool — PED + Reporting

Strumento interno dell'agenzia OFG per **automatizzare la creazione dei Piani Editoriali (PED)** per i clienti e il **reporting** delle performance.

## A cosa serve
- 🧠 **Memoria cliente straprecisa** — ogni cliente ha la sua scheda (tono di voce, regole, esempi approvati), tenuta separata dagli altri.
- 📅 **Piani Editoriali** — generati su misura per ogni cliente, con revisione del team.
- 📊 **Report** — performance ADS e social, da file Excel/CSV e (in futuro) collegando Meta e Google.

## Com'è organizzato
- `app/` → l'interfaccia (quello che si vede e si usa, in Streamlit)
- `core/` → la logica e gli "agenti" AI (memoria, PED, report)

## Chiavi e sicurezza
Le chiavi API **non vanno mai scritte nel codice**. Si copiano dentro un file `.env`
(che resta solo sul tuo PC ed è escluso dal controllo versione). Vedi `.env.example`
per l'elenco delle chiavi necessarie.

## Come si avvia (in locale)
1. Installare le dipendenze: `pip install -r requirements.txt`
2. Copiare `.env.example` in `.env` e inserire le proprie chiavi
3. Avviare: `streamlit run app/Home.py`

> Progetto in costruzione — Tappa 0: fondamenta.
