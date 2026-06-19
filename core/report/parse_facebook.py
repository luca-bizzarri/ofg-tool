# -*- coding: utf-8 -*-
"""
Parser del report Facebook esportato da Agorapulse (PDF testuale).

Struttura molto vicina a Instagram, con differenze:
- engagement: Reazioni / Commenti / Condivisioni / Messaggi privati (niente Saved);
- formati pubblicazione: Storie / Stati / Link / Foto / Video;
- top post con Clic e Altri clic (al posto di Like/Commenti/Saved);
- sezione Video views;
- niente hashtag, niente stories dedicate.
I numeri usano la virgola come separatore delle migliaia (es. "1,813").
Deterministico: nessuna AI sui numeri.
"""
import re

from core.report.parse_instagram import EN_MONTHS, _pct, _tone, _pdf_text, _search, _VAL, _DLT


def _fnum(tok):
    """Numero da token Facebook (virgola = migliaia): '1,813'->1813, '2.5K'->2500."""
    if tok is None:
        return None
    t = str(tok).strip().replace("%", "").replace(",", "")  # togli separatore migliaia
    if t in ("—", "-", "", "No data"):
        return None
    mult = 1
    if t[-1:].upper() == "K":
        mult, t = 1000, t[:-1]
    elif t[-1:].upper() == "M":
        mult, t = 1_000_000, t[:-1]
    try:
        v = float(t) * mult
        return int(v) if v == int(v) else round(v, 2)
    except ValueError:
        return None


def _disp(tok):
    """Display all'italiana: K/M -> virgola decimale; interi -> punto migliaia."""
    t = str(tok).strip() if tok is not None else ""
    if not t or t in ("—", "No data"):
        return t or ""
    if t[-1:].upper() in ("K", "M"):
        return t.replace(".", ",")
    v = _fnum(t)
    if v is None:
        return t
    if isinstance(v, int):
        return f"{v:,}".replace(",", ".")
    return str(v).replace(".", ",")


def parse(pdf_path):
    text = _pdf_text(pdf_path)
    missing = []
    data = {"id": "facebook", "label": "Facebook", "type": "facebook",
            "meta": {}, "kpis": [], "split": {}, "engagement_breakdown": [],
            "rates": [], "audience_growth": [], "publishing_mix": [],
            "top_content": [], "stories": [], "hashtags": [], "geo": [],
            "community": [], "roadmap": {"continuare": [], "potenziare": [], "correggere": [], "testare": []}}

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    brand = lines[0] if lines else "Cliente"
    period = ""
    mp = re.search(r"([A-Za-z]+)\s+(\d+),\s+(\d+)\s*-\s*([A-Za-z]+)\s+(\d+),\s+(\d+)", text)
    if mp:
        m1, d1, y1, m2, d2, _ = mp.groups()
        mon1, mon2 = EN_MONTHS.get(m1.lower(), m1.lower()), EN_MONTHS.get(m2.lower(), m2.lower())
        period = f"{d1}-{d2} {mon1} {y1}" if mon1 == mon2 else f"{d1} {mon1} - {d2} {mon2} {y1}"
    data["meta"] = {"brand": brand, "channel": "Facebook", "period": period, "source": "Export Facebook / Agorapulse"}

    def kpi(_id, label, val, delta):
        return {"id": _id, "label": label, "value": _disp(val), "delta": _pct(delta),
                "tone": _tone(_pct(delta)), "detail": "", "action": ""}

    ov = _search(rf"Total followers\s+{_VAL}\s+{_DLT}.*?Engagement\s+{_VAL}\s+{_DLT}"
                 rf".*?Views\s+{_VAL}\s+{_DLT}.*?Mentions\s+{_VAL}\s+{_DLT}", text)
    vw = _search(rf"Views\s+{_VAL}\s+{_DLT}\s+Organic views\s+{_VAL}\s+{_DLT}\s+Paid views\s+{_VAL}\s+{_DLT}", text)
    pi = _search(rf"Published posts\s+{_VAL}\s+{_DLT}\s*Posts views\s+{_VAL}\s+{_DLT}\s*Posts engagement\s+{_VAL}\s+{_DLT}", text)
    vv = _search(rf"Video views\s+{_VAL}\s+{_VAL}\s+{_VAL}\s+{_DLT}", text)

    if ov:
        data["kpis"] += [kpi("followers", "Follower totali", ov[0], ov[1]),
                         kpi("engagement", "Engagement totale", ov[2], ov[3]),
                         kpi("views", "Views totali", ov[4], ov[5])]
    if vw:
        data["kpis"] += [kpi("organic_views", "Views organiche", vw[2], vw[3]),
                         kpi("paid_views", "Views paid", vw[4], vw[5])]
    if ov:
        data["kpis"].append(kpi("mentions", "Mention", ov[6], ov[7]))
    if pi:
        data["kpis"] += [kpi("published", "Post pubblicati", pi[0], pi[1]),
                         kpi("post_views", "Views sui post", pi[2], pi[3]),
                         kpi("post_engagement", "Engagement post", pi[4], pi[5])]
    if vv:
        data["kpis"].append(kpi("video_views", "Visualizzazioni video", vv[2], vv[3]))

    # engagement breakdown (Reazioni/Commenti/Condivisioni/Messaggi)
    eb = [("Reazioni", "Reactions"), ("Commenti", "Comments"), ("Condivisioni", "Shares"), ("Messaggi privati", "Private messages")]
    for it, en in eb:
        g = _search(rf"{en}\s+([\d—,]+)\s+([\d—,]+)\s+([\d—,]+)\s+{_DLT}", text)
        if g:
            data["engagement_breakdown"].append({"label": it, "organic": _fnum(g[0]), "paid": _fnum(g[1]),
                                                 "total": _fnum(g[2]), "variation": _pct(g[3])})
    te = _search(rf"Total engagement\s+(\d+)\s+(\d+)\s+(\d+)\s+{_DLT}", text)

    if vw:
        data["split"]["views"] = [{"label": "Organiche", "value": _fnum(vw[2]), "display": _disp(vw[2])},
                                  {"label": "Paid", "value": _fnum(vw[4]), "display": _disp(vw[4])}]
    if te:
        pm = next((e for e in data["engagement_breakdown"] if e["label"] == "Messaggi privati"), None)
        sp = [{"label": "Organico", "value": _fnum(te[0]), "display": te[0]},
              {"label": "Paid", "value": _fnum(te[1]), "display": te[1]}]
        if pm and pm.get("total"):
            sp.append({"label": "Messaggi non ripartiti", "value": pm["total"], "display": str(pm["total"])})
        data["split"]["engagement"] = sp
    rc = _search(rf"Average reach\s+{_VAL}\s+{_DLT}\s+Average organic reach\s+{_VAL}\s+{_DLT}\s+Average paid reach\s+{_VAL}\s+{_DLT}", text)
    if rc:
        data["split"]["reach"] = [{"label": "Reach organica media", "value": _fnum(rc[2]), "display": _disp(rc[2])},
                                  {"label": "Reach paid media", "value": _fnum(rc[4]), "display": _disp(rc[4])}]

    rates = re.findall(rf"Eng\. rate[^0-9]*([\d.,]+%)\s+([\d.,]+%)\s+([\d.,]+%)\s+{_DLT}", text)
    for i, mname in [(0, "Engagement rate per view"), (1, "Engagement rate per reach")]:
        if len(rates) > i:
            r = rates[i]
            data["rates"].append({"metric": mname, "organic": r[0].replace(".", ","), "paid": r[1].replace(".", ","),
                                  "total": r[2].replace(".", ","), "variation": _pct(r[3]), "insight": ""})

    ag = _search(r"Followers\s+(\d+)\s+(\d+)\s+(\d+)\s*\n[^\n]*New Lost Net growth", text)
    if ag:
        data["audience_growth"] = [{"label": "Nuovi follower", "value": _fnum(ag[0])},
                                   {"label": "Follower persi", "value": _fnum(ag[1])},
                                   {"label": "Crescita netta", "value": _fnum(ag[2])}]

    fmt = [("Storie", "Stories"), ("Stati", "Statuses"), ("Link", "Links"), ("Foto", "Photos"), ("Video", "Videos")]
    counts = {}
    for it, en in fmt:
        g = _search(rf"{en}\s+(\d+)\s+{_DLT}", text)
        if g:
            counts[it] = _fnum(g[0])
            data["publishing_mix"].append({"format": it, "posts": _fnum(g[0]), "variation": _pct(g[1]), "avg_engagement": 0, "share": 0.0})
    tot = sum(v for v in counts.values() if v) or 0
    for row in data["publishing_mix"]:
        row["share"] = round((row["posts"] / tot) * 100, 1) if tot and row["posts"] else 0.0

    # top content (Clicks / Other clicks invece di Like/Saved)
    posts = re.findall(
        r"(\d{2}/\d{2}/\d{2})\s+(\d{1,2}:\d{2})\s+Views\s+(\d+)\s+Reach\s+(\d+)\s+Engagement\s+(\d+)"
        r"\s+Clicks\s+(\d+)\s+Other clicks\s+(\d+)\s+Eng\. rate per view\s+([\d.,]+%)\s+Eng\. rate per reach\s+([\d.,]+%)", text)
    stat_iters = list(re.finditer(
        r"\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}\s+Views\s+\d+\s+Reach\s+\d+\s+Engagement\s+\d+\s+Clicks\s+\d+\s+Other clicks\s+\d+"
        r"\s+Eng\. rate per view\s+[\d.,]+%\s+Eng\. rate per reach\s+[\d.,]+%", text))
    tail = text[stat_iters[-1].end():] if stat_iters else ""
    descs = re.findall(r"(.+?)\s*No label\s*(Image|Video|Link|Status|Story)", tail, re.DOTALL)
    tmap = {"Image": "Immagine", "Video": "Video", "Link": "Link", "Status": "Stato", "Story": "Storia"}
    for i, p in enumerate(posts):
        desc = re.sub(r"\s+", " ", descs[i][0].strip()) if i < len(descs) else ""
        ptype = tmap.get(descs[i][1], "Post") if i < len(descs) else "Post"
        data["top_content"].append({
            "date": p[0], "time": p[1], "type": ptype, "topic": (desc.split(".")[0][:48]).strip(), "description": desc,
            "views": _fnum(p[2]), "reach": _fnum(p[3]), "engagement": _fnum(p[4]),
            "clicks": _fnum(p[5]), "other_clicks": _fnum(p[6]), "saved": None,
            "er_view": _fnum(p[7].replace("%", "").replace(",", ".")), "er_reach": _fnum(p[8].replace("%", "").replace(",", ".")), "insight": ""})

    cm = _search(rf"Replies sent\s+{_VAL}\s+{_DLT}.*?Reviewed items\s+{_VAL}\s+{_DLT}"
                 rf".*?Deleted/Hidden items\s+{_VAL}\s+{_DLT}.*?Average response time\s+(—|[\d.,]+\s*\w*)\s+{_DLT}", text)
    if cm:
        data["community"] = [{"label": "Replies sent", "value": _disp(cm[0]), "variation": _pct(cm[1])},
                             {"label": "Reviewed items", "value": _disp(cm[2]), "variation": _pct(cm[3])},
                             {"label": "Deleted/Hidden items", "value": _disp(cm[4]), "variation": _pct(cm[5])},
                             {"label": "Average response time", "value": (cm[6] or "—").strip(), "variation": _pct(cm[7])}]

    missing.append("Distribuzione follower per citta'/paese (nel PDF e' solo un grafico)")
    missing.append("Timing/heatmap orari (solo grafico nel PDF)")
    missing.append("Testi narrativi (da generare con il motore di tono)")
    data["missing_data"] = missing
    return data
