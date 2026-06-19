# -*- coding: utf-8 -*-
"""
Parser degli export LinkedIn (.xls nativi della pagina aziendale):
- followers : "Nuovi follower" + audience follower (funzione, anzianita', settore,
              dimensioni azienda, localita');
- content   : "Metriche" (impressioni, clic, reazioni, commenti, diffusioni) e
              "Tutti i post" (top post);
- visitors  : "Statistiche sui visitatori" (visite pagina, visitatori unici) +
              audience visitatori.

Ogni file e' OPZIONALE: si estrae quello che c'e', il resto va in missing_data.
Deterministico, nessuna AI sui numeri.
"""
import pandas as pd

MONTHS_IT = {1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
             7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"}


def _itd(n):
    """Display all'italiana con separatore migliaia ('.')."""
    if n is None:
        return ""
    try:
        return f"{int(round(float(n))):,}".replace(",", ".")
    except (ValueError, TypeError):
        return str(n)


def _i(x):
    """Converte in int gestendo NaN/None/stringhe (NaN -> 0)."""
    v = pd.to_numeric(x, errors="coerce")
    return int(v) if pd.notna(v) else 0


def _sum(df, col):
    if df is None or col not in df.columns:
        return None
    return int(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def _dim(df, val_col, top=8):
    """Lista [{label,value}] da un foglio a 2 colonne (etichetta + valore)."""
    out = []
    if df is None or df.shape[1] < 2:
        return out
    label_col = df.columns[0]
    if val_col not in df.columns:
        val_col = df.columns[1]
    d = df[[label_col, val_col]].copy()
    d[val_col] = pd.to_numeric(d[val_col], errors="coerce").fillna(0)
    d = d[d[val_col] > 0].sort_values(val_col, ascending=False).head(top)
    for _, r in d.iterrows():
        out.append({"label": str(r[label_col]).strip(), "value": int(r[val_col])})
    return out


def _period(df, date_col="Data"):
    if df is None or date_col not in df.columns:
        return ""
    s = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False).dropna()
    if s.empty:
        return ""
    a, b = s.min(), s.max()
    if a.month == b.month and a.year == b.year:
        return f"{a.day}-{b.day} {MONTHS_IT.get(a.month, '')} {a.year}"
    return f"{a.day} {MONTHS_IT.get(a.month,'')} - {b.day} {MONTHS_IT.get(b.month,'')} {b.year}"


def _kpi(_id, label, value):
    return {"id": _id, "label": label, "value": _itd(value), "delta": "", "tone": "neutral",
            "detail": "", "action": ""}


def parse(followers=None, content=None, visitors=None):
    """Costruisce il canale LinkedIn dai file forniti (anche solo alcuni)."""
    ch = {"id": "linkedin", "label": "LinkedIn", "type": "linkedin",
          "meta": {"channel": "LinkedIn", "period": "", "source": "Export LinkedIn"},
          "kpis": [], "follower_growth": [], "engagement_breakdown": [],
          "audience": {}, "visitors_kpis": [], "visitor_audience": {},
          "top_post": [], "missing_data": []}
    period = ""

    # --- FOLLOWERS ---
    new_followers = imp = clicks = reazioni = commenti = diffusioni = None
    if followers is not None:
        xf = pd.ExcelFile(followers)
        def sh(name):
            return xf.parse(name) if name in xf.sheet_names else None
        nf = sh("Nuovi follower")
        period = _period(nf) or period
        org = _sum(nf, "Follower organici")
        spo = _sum(nf, "Follower sponsorizzati")
        inv = _sum(nf, "Follower invitati automaticamente")
        new_followers = _sum(nf, "Follower totali")
        ch["follower_growth"] = [r for r in [
            {"label": "Organici", "value": org or 0},
            {"label": "Sponsorizzati", "value": spo or 0},
            {"label": "Invitati", "value": inv or 0},
        ] if r["value"] is not None]
        ch["audience"] = {
            "funzione": _dim(sh("Funzione lavorativa"), "Follower totali"),
            "anzianita": _dim(sh("Anzianità"), "Follower totali"),
            "settore": _dim(sh("Settore"), "Follower totali"),
            "dimensioni": _dim(sh("Dimensioni dell’azienda"), "Follower totali"),
            "localita": _dim(sh("Località"), "Follower totali"),
        }
    else:
        ch["missing_data"].append("Follower e audience (file followers non caricato)")

    # --- CONTENT ---
    if content is not None:
        xc = pd.ExcelFile(content)
        met = pd.read_excel(content, sheet_name="Metriche", header=1) if "Metriche" in xc.sheet_names else None
        if met is not None:
            period = _period(met) or period
            imp = _sum(met, "Impressioni (totale)")
            clicks = _sum(met, "Clic (totale)")
            reazioni = _sum(met, "Reazioni (totale)")
            commenti = _sum(met, "Commenti (totale)")
            diffusioni = _sum(met, "Diffusioni post (totali)")
            ch["engagement_breakdown"] = [
                {"label": "Reazioni", "organic": _sum(met, "Reazioni (organiche)"), "paid": _sum(met, "Reazioni (sponsorizzate)"), "total": reazioni, "variation": ""},
                {"label": "Commenti", "organic": _sum(met, "Commenti (organici)"), "paid": _sum(met, "Commenti (sponsorizzati)"), "total": commenti, "variation": ""},
                {"label": "Diffusioni", "organic": _sum(met, "Diffusioni post (organiche)"), "paid": _sum(met, "Diffusioni post (sponsorizzate)"), "total": diffusioni, "variation": ""},
                {"label": "Clic", "organic": _sum(met, "Clic (organici)"), "paid": _sum(met, "Clic (sponsorizzati)"), "total": clicks, "variation": ""},
            ]
        posts = pd.read_excel(content, sheet_name="Tutti i post", header=1) if "Tutti i post" in xc.sheet_names else None
        if posts is not None:
            posts = posts.copy()
            posts["_imp"] = pd.to_numeric(posts.get("Impressioni"), errors="coerce").fillna(0)
            for _, r in posts.sort_values("_imp", ascending=False).head(5).iterrows():
                titolo = str(r.get("Titolo del post", "") or "").replace("\n", " ").strip()
                d = r.get("Data di creazione", "")
                try:
                    d = pd.to_datetime(d).strftime("%d/%m/%y")
                except Exception:
                    d = str(d)[:10]
                ctr = pd.to_numeric(r.get("Percentuale di clic (CTR)"), errors="coerce")
                ch["top_post"].append({
                    "date": d, "type": str(r.get("Tipo di contenuto", "") or "Post"),
                    "topic": titolo[:60], "description": titolo,
                    "impressions": _i(r["_imp"]), "views": _i(r.get("Visualizzazioni")),
                    "clicks": _i(r.get("Clic")),
                    "ctr": (round(float(ctr) * 100, 2) if pd.notna(ctr) and float(ctr) < 1 else (round(float(ctr), 2) if pd.notna(ctr) else "")),
                    "comments": _i(r.get("Commenti")),
                    "reposts": _i(r.get("Diffusioni post")),
                    "new_followers": _i(r.get("Nuovi follower")),
                })
    else:
        ch["missing_data"].append("Impressioni, clic e post (file content non caricato)")

    # --- VISITORS ---
    if visitors is not None:
        xv = pd.ExcelFile(visitors)
        def shv(name):
            return xv.parse(name) if name in xv.sheet_names else None
        stat = shv("Statistiche sui visitatori")
        period = period or _period(stat)
        pv = _sum(stat, "Totale visualizzazioni della pagina (totale)")
        uv = _sum(stat, "Totale visitatori unici (totale)")
        ch["visitors_kpis"] = [
            {"label": "Visite pagina", "value": _itd(pv)},
            {"label": "Visitatori unici", "value": _itd(uv)},
        ]
        ch["visitor_audience"] = {
            "funzione": _dim(shv("Funzione lavorativa"), "Visualizzazioni totali"),
            "settore": _dim(shv("Settore"), "Visualizzazioni totali"),
            "localita": _dim(shv("Località"), "Visualizzazioni totali"),
        }
    else:
        pv = uv = None
        ch["missing_data"].append("Visite pagina e visitatori (file visitors non caricato)")

    # --- KPI principali ---
    if new_followers is not None:
        ch["kpis"].append(_kpi("new_followers", "Nuovi follower", new_followers))
    if imp is not None:
        ch["kpis"].append(_kpi("impressions", "Impressioni", imp))
    if clicks is not None:
        ch["kpis"].append(_kpi("clicks", "Clic", clicks))
    eng = sum(v for v in [reazioni, commenti, diffusioni] if v) if any([reazioni, commenti, diffusioni]) else None
    if eng is not None:
        ch["kpis"].append(_kpi("engagement", "Interazioni", eng))
    if visitors is not None and pv is not None:
        ch["kpis"].append(_kpi("page_views", "Visite pagina", pv))
        ch["kpis"].append(_kpi("unique_visitors", "Visitatori unici", uv))

    ch["meta"]["period"] = period
    return ch
