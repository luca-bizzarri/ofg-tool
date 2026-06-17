"""
Aree IDEAZIONE e CAMPAGNE ADV di OFG Tool.
Generazione creativa ancorata alla scheda cliente (tono di voce, brand, regole).
"""
from core import rag_engine as rag

IDEA_TYPES = [
    "Idee per Reel", "Idee per Caroselli", "Idee per Post statici", "Idee per Stories",
    "Video promo", "Contenuti per festivita'", "Format editoriali", "Nuove rubriche social (trend)",
    "Concept campagne ADV", "Lancio nuovo prodotto",
]


def _ctx(client_id):
    res = rag.get_client_context(client_id, "tono di voce, brand, posizionamento, ICP, regole, esempi", k=12)
    return res.get("context", ""), res.get("metadata", {}).get("sources", [])


def generate_ideazione(client_id, tipologia_idee, obiettivo, piattaforme, note=""):
    """Genera piu' direzioni creative diverse. Ritorna (testo, fonti)."""
    context, fonti = _ctx(client_id)
    blacklist = rag.extract_constraints(client_id)
    prompt = (
        f"Sei un Creative & Content Strategist senior. Proponi IDEE creative per: {tipologia_idee}.\n\n"
        f"## CONTESTO CLIENTE (base assoluta, non inventare):\n{context or 'Nessun contesto.'}\n\n"
        f"## BRIEF: Obiettivo={obiettivo} | Piattaforme={', '.join(piattaforme)} | Note={note or '-'}\n\n"
        f"## OUTPUT RICHIESTO (struttura obbligatoria):\n"
        f"OBIETTIVO CREATIVO: breve sintesi dell'idea strategica.\n"
        f"DIREZIONE 1 - [Nome concept]: descrizione + esempi di hook + possibile sviluppo. (taglio piu' ISTITUZIONALE)\n"
        f"DIREZIONE 2 - [Nome concept]: descrizione + esempi di hook + possibile sviluppo. (taglio piu' CREATIVO)\n"
        f"DIREZIONE 3 - [Nome concept]: descrizione + esempi di hook + possibile sviluppo. (taglio piu' CONVERSION/SOCIAL)\n"
        f"PROPOSTA CONSIGLIATA: quale scegliere e perche'.\n\n"
        f"## REGOLE: le direzioni devono essere DIVERSE tra loro (non variazioni della stessa frase). "
        f"NON usare mai: {', '.join(blacklist) if blacklist else 'nessuna'}. Niente frasi generiche."
    )
    return rag.llm.invoke(prompt).content, fonti


def generate_adv(client_id, nome_promo, obiettivo, timing, piattaforme, scontistica, messaggi, email_si=False, concept="", note=""):
    """Genera una struttura completa di campagna ADV. Ritorna (testo, fonti)."""
    context, fonti = _ctx(client_id)
    blacklist = rag.extract_constraints(client_id)
    email_block = (
        "MATERIALE EMAIL MARKETING: per ogni email utile fornisci Head, Subhead e CTA.\n" if email_si else ""
    )
    prompt = (
        f"Sei un Creative Strategist + Media Buyer senior. Sviluppa la campagna ADV.\n\n"
        f"## CONTESTO CLIENTE (base assoluta):\n{context or 'Nessun contesto.'}\n\n"
        f"## BRIEF CAMPAGNA:\n"
        f"Nome promo: {nome_promo or '-'} | Obiettivo: {obiettivo} | Timing: {timing or '-'}\n"
        f"Piattaforme: {', '.join(piattaforme)} | Scontistica: {scontistica or '-'}\n"
        f"Messaggi/concetti chiave: {messaggi or '-'}\n"
        f"Concept gia' fornito (se presente, NON ripeterlo nell'output): {concept or '-'}\n"
        f"Note: {note or '-'}\n\n"
        f"## OUTPUT RICHIESTO (struttura completa):\n"
        f"{'CONCEPT ADV: (ometti se gia fornito sopra)' if not concept else ''}\n"
        f"ANGOLO CREATIVO: descrizione.\n"
        f"PRIMARY TEXT: testo principale.\n"
        f"HEADLINE: titolo breve.\n"
        f"DESCRIPTION: descrizione breve.\n"
        f"CTA: call to action.\n"
        f"VARIANTI HOOK: almeno 5 alternative.\n"
        f"TEST A/B: proponi angoli diversi da testare.\n"
        f"{email_block}"
        f"\n## REGOLE: NON usare mai: {', '.join(blacklist) if blacklist else 'nessuna'}. "
        f"Copy pronti, nello stile e tono di voce del brand."
    )
    return rag.llm.invoke(prompt).content, fonti
