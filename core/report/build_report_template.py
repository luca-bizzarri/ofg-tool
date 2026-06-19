# -*- coding: utf-8 -*-
"""
Builder del TEMPLATE MULTI CANALE (template_report.html).

Riusa <head> + <style> del template mono-canale (template_instagram.html) e
sostituisce body e script con una shell guidata dai dati:
- barra in alto con una TAB per canale (Instagram, LinkedIn, ...),
- sidebar con le sezioni del canale attivo,
- main con le sezioni del canale attivo.

Solo il canale attivo e' montato nel DOM: cosi' gli ID dei grafici (kpiGrid,
splitChart, ...) non vanno mai in conflitto e si riusa il motore esistente.

DATA atteso dal renderer:
{
  "meta": {"brand","period",...},
  "channels": [ { "id","label","type":"instagram", ...campi del canale... } ],
}
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "template_instagram.html")
OUT = os.path.join(HERE, "template_report.html")

EXTRA_CSS = """
<style>
  /* --- multi canale: barra superiore con le tab dei social --- */
  .topbar { position: sticky; top: 0; z-index: 30; display:flex; align-items:center; gap:18px;
            padding: 12px 22px; background: var(--navy); color:#fff; box-shadow: 0 6px 18px rgba(0,0,0,.12); }
  .topbar-logo { height: 34px; width:auto; }
  .topbar-title { display:flex; flex-direction:column; line-height:1.1; }
  .topbar-title strong { font-size:15px; } .topbar-title span { font-size:12px; color:rgba(255,255,255,.7); }
  .tabbar { display:flex; gap:8px; margin-left:auto; flex-wrap:wrap; }
  .tabbar .tab { border:1px solid rgba(255,255,255,.22); background:rgba(255,255,255,.08); color:#fff;
                 padding:9px 15px; border-radius:999px; font-weight:800; font-size:13px; cursor:pointer; transition:.2s; }
  .tabbar .tab:hover { background:rgba(255,255,255,.18); }
  .tabbar .tab.active { background:var(--purple); border-color:var(--purple); color:#fff; }
  .app { min-height: calc(100vh - 58px); }
  aside { height: calc(100vh - 58px); top: 58px; }
  .donut:after { content: none !important; }
  .donut-center { position:absolute; inset:27px; border-radius:50%; background:#fff; display:grid;
                  place-items:center; font-size:34px; font-weight:900; letter-spacing:-.05em; }
  .empty-note { color:var(--muted); font-style:italic; font-size:13px; margin-top:10px; }
</style>
"""

# ---------------------------------------------------------------------------
# BODY (shell) + SCRIPT (engine). Plain string: niente .format(), i {{...}}
# restano segnaposto per render.py.
# ---------------------------------------------------------------------------
BODY_AND_SCRIPT = r"""
<body>
<header class="topbar">
  <img class="topbar-logo" src="{{LOGO}}" alt="logo" onerror="this.style.display='none'"/>
  <div class="topbar-title"><strong id="repBrand"></strong><span id="repPeriod"></span></div>
  <nav class="tabbar" id="tabbar"></nav>
</header>
<div class="app">
  <aside>
    <div class="brandmark"><img class="brand-logo" src="{{LOGO}}" alt="logo" onerror="this.style.display='none'"/></div>
    <select id="mobileNav" class="mobile-nav" style="display:none"></select>
    <nav id="sideNav"></nav>
    <div class="side-note"><strong>Report</strong><span id="sideNote"></span></div>
  </aside>
  <main id="main"></main>
</div>

<script>
const DATA = {{DATA}};
let D = null; // canale attivo

// ---------- helper ----------
function fmt(n){ if(n===null||n===undefined) return '—'; if(typeof n==='string') return n; return n.toLocaleString('it-IT'); }
function pctw(value,max){ return max ? Math.max(0,Math.min(100,(value/max)*100)) : 0; }
function toneClass(delta){ if(!delta||delta==='No data'||delta==='—') return 'neutral'; return String(delta).trim().startsWith('+')?'green':'amber'; }
function makeDelta(delta,tone){ return `<span class="delta ${tone||toneClass(delta)}">${delta||'—'}</span>`; }
function tagClass(type){ const t=String(type).toLowerCase(); if(t.includes('reel'))return 'reel'; if(t.includes('immagine')||t.includes('image'))return 'image'; if(t.includes('carosello')||t.includes('carousel'))return 'carousel'; return ''; }
function barChart(el,data,options={}){ if(!el) return; const max=options.max||Math.max(...data.map(d=>d.value||0),1); const fc=options.fillClass||'';
  el.innerHTML=data.map(d=>`<div class="bar-row"><div class="bar-label" title="${d.label}">${d.label}</div><div class="track"><div class="fill ${fc}" style="width:${pctw(d.value,max)}%"></div></div><div class="bar-value">${d.display||fmt(d.value)}</div></div>`).join(''); }
function has(v){ return v && (Array.isArray(v)? v.length>0 : (typeof v==='object'? Object.keys(v).length>0 : String(v).trim()!=='')); }
function sectionHead(t,s){ return `<div class="section-head"><div><h2>${t}</h2>${s?`<p>${s}</p>`:''}</div></div>`; }
function byId(id){ return document.getElementById(id); }
function wireKpis(ch){
  const kpiGrid=byId('kpiGrid'), kpiInsight=byId('kpiInsight');
  if(!kpiGrid||!ch.kpis) return;
  const showKpi=(k)=>{ kpiInsight.innerHTML=`<strong>${k.label} · ${k.value}</strong><p>${k.detail||'—'}</p>${k.action?`<p style="margin-top:8px"><b>Azione:</b> ${k.action}</p>`:''}`; };
  kpiGrid.innerHTML=ch.kpis.map((k,i)=>`<button class="kpi ${i===0?'active':''}" data-id="${k.id}"><span class="label">${k.label}</span><span><span class="value">${k.value}</span>${makeDelta(k.delta,k.tone)}</span></button>`).join('');
  showKpi(ch.kpis[0]); kpiGrid.querySelectorAll('.kpi').forEach(b=>b.addEventListener('click',()=>{ kpiGrid.querySelectorAll('.kpi').forEach(x=>x.classList.remove('active')); b.classList.add('active'); showKpi(ch.kpis.find(k=>k.id===b.dataset.id)); }));
}
function considerazioniHTML(N){ if(!has(N.considerazioni)) return ''; const c=N.considerazioni;
  return `<section id="considerazioni" data-label="Considerazioni">${sectionHead('Considerazioni e lettura dei risultati','Una lettura qualitativa che affianca i numeri e ne chiarisce il significato.')}
  <div class="narrative-grid"><div class="card callout"><h3>Considerazione generale</h3>${(c.generale||[]).map(p=>`<p style="margin-top:8px">${p}</p>`).join('')}</div>
  <div class="soft-index">${(c.soft_index||[]).map(s=>`<div class="metric-row"><div><strong>${s.title}</strong><span>${s.desc}</span></div><div class="number">${s.value}</div></div>`).join('')}</div></div>
  <div class="grid four" style="margin-top:18px">${c.performance?`<div class="narrative-card"><h3>Lettura delle performance</h3><p>${c.performance}</p></div>`:''}${c.forza?`<div class="narrative-card"><h3>Punti di forza</h3><p>${c.forza}</p></div>`:''}${c.attenzione?`<div class="narrative-card"><h3>Aree da osservare</h3><p>${c.attenzione}</p></div>`:''}${c.sintesi?`<div class="narrative-card"><h3>In sintesi</h3><p>${c.sintesi}</p></div>`:''}</div></section>`; }
function conclusioniHTML(N){ if(!has(N.conclusioni)) return ''; const cc=N.conclusioni;
  return `<section id="conclusioni" data-label="Conclusioni">${sectionHead('Conclusioni','')}
  <div class="grid two"><div class="card callout"><h3>Lettura conclusiva</h3>${(cc.lettura||[]).map(p=>`<p style="margin-top:8px">${p}</p>`).join('')}</div>
  <div class="card"><h3>Direzione consigliata</h3><div class="metric-list">${(cc.direzione||[]).map((d,i)=>`<div class="metric-row"><div><strong>${d.title}</strong><span>${d.desc}</span></div><div class="number">0${i+1}</div></div>`).join('')}</div></div></section>`; }

// ---------- markup per tipo di canale ----------
const SECTION_HTML = {
  instagram: (ch) => {
    const N = ch.narrative || {};
    const roadmapHas = ch.roadmap && Object.values(ch.roadmap).some(v => v && v.length);
    return `
    <section id="overview" data-label="Panoramica" class="hero">
      <div class="eyebrow">${DATA.meta.brand || ''}</div>
      <h2>Report ${ch.label}</h2>
      <p>${N.hero || (DATA.meta.period ? 'Periodo: ' + DATA.meta.period : '')}</p>
    </section>

    ${has(N.considerazioni) ? `
    <section id="considerazioni" data-label="Considerazioni">
      ${sectionHead('Considerazioni e lettura dei risultati','Una lettura qualitativa che affianca i numeri e ne chiarisce il significato.')}
      <div class="narrative-grid">
        <div class="card callout"><h3>Considerazione generale</h3>${(N.considerazioni.generale||[]).map(p=>`<p style="margin-top:8px">${p}</p>`).join('')}</div>
        <div class="soft-index">${(N.considerazioni.soft_index||[]).map(s=>`<div class="metric-row"><div><strong>${s.title}</strong><span>${s.desc}</span></div><div class="number">${s.value}</div></div>`).join('')}</div>
      </div>
      <div class="grid four" style="margin-top:18px">
        ${N.considerazioni.performance?`<div class="narrative-card"><h3>Lettura delle performance</h3><p>${N.considerazioni.performance}</p></div>`:''}
        ${N.considerazioni.forza?`<div class="narrative-card"><h3>Punti di forza</h3><p>${N.considerazioni.forza}</p></div>`:''}
        ${N.considerazioni.attenzione?`<div class="narrative-card"><h3>Aree da osservare</h3><p>${N.considerazioni.attenzione}</p></div>`:''}
        ${N.considerazioni.sintesi?`<div class="narrative-card"><h3>In sintesi</h3><p>${N.considerazioni.sintesi}</p></div>`:''}
      </div>
    </section>`:''}

    <section id="kpi" data-label="KPI">
      ${sectionHead('Dashboard KPI','Vista sintetica del periodo. Clicca una card per leggere l\'interpretazione.')}
      <div id="kpiGrid" class="grid kpis"></div>
      <div id="kpiInsight" class="card insight-panel" style="margin-top:18px"></div>
    </section>

    ${has(ch.split)?`
    <section id="paid-organic" data-label="Paid vs Organic">
      ${sectionHead('Paid vs Organic','Il paid genera scala, l\'organico segnala la qualita\' dell\'attenzione.')}
      <div class="grid two">
        <div class="card"><h3>Distribuzione per canale</h3><div class="split-tools" id="splitButtons"></div><div id="splitChart" class="bar-chart"></div></div>
        <div class="card"><h3>Engagement rate</h3><div class="table-wrap"><table id="rateTable"><thead><tr><th>Metrica</th><th>Organico</th><th>Paid</th><th>Totale</th><th>Insight</th></tr></thead><tbody></tbody></table></div></div>
      </div>
      <div class="grid two" style="margin-top:18px">
        <div class="card"><h3>Composizione engagement</h3><div id="engagementChart" class="bar-chart"></div></div>
        ${N.insight_centrale?`<div class="card callout"><h3>Insight centrale</h3><p class="quote">${N.insight_centrale.quote||''}</p><p style="margin-top:12px">${N.insight_centrale.body||''}</p></div>`:''}
      </div>
    </section>`:''}

    <section id="audience" data-label="Audience">
      ${sectionHead('Audience e crescita','Profilo e crescita del pubblico nel periodo.')}
      <div class="grid three">
        <div class="card"><h3>Crescita follower</h3><div id="growthChart" class="bar-chart"></div></div>
        <div class="card"><h3>Distribuzione citta\'</h3><div id="geoChart" class="bar-chart"></div><div id="geoNote"></div></div>
        <div class="card"><h3>Profilo audience</h3><div class="metric-list" id="audienceProfile"></div></div>
      </div>
    </section>

    ${has(ch.top_content)?`
    <section id="contenuti" data-label="Contenuti">
      ${sectionHead('Performance contenuti','Contenuti pubblicati nel periodo e loro performance.')}
      <div class="grid two">
        <div class="card"><h3>Mix di pubblicazione</h3><div class="donut-wrap"><div class="donut" id="mixDonut"><span class="donut-center" id="mixTotal"></span></div><div class="legend" id="mixLegend"></div></div></div>
        <div class="card"><h3>Formato per engagement medio</h3><div id="formatEngagementChart" class="bar-chart"></div></div>
      </div>
      <div class="section-head"><div><h2 style="font-size:24px">Top content</h2></div><div class="pill-row" id="contentFilters"></div></div>
      <div id="contentCards" class="grid three"></div>
      <div class="card" style="margin-top:18px"><h3>Tabella contenuti ordinabile</h3><p style="margin-bottom:12px">Clicca sulle intestazioni per ordinare.</p>
        <div class="table-wrap"><table id="contentTable"><thead><tr><th data-sort="date">Data</th><th data-sort="type">Formato</th><th data-sort="topic">Tema</th><th data-sort="views">Views</th><th data-sort="reach">Reach</th><th data-sort="engagement">Eng.</th><th data-sort="er_reach">ER reach</th><th>Insight</th></tr></thead><tbody></tbody></table></div></div>
      ${has(ch.stories)?`<div class="grid two" style="margin-top:18px"><div class="card"><h3>Stories migliori</h3><div id="storyChart" class="bar-chart"></div></div></div>`:''}
    </section>`:''}

    ${has(ch.hashtags)?`
    <section id="hashtag" data-label="Hashtag">
      ${sectionHead('Hashtag e interazioni','Hashtag con piu\' interazioni nel periodo.')}
      <div class="grid two"><div class="card"><h3>Classifica hashtag</h3><div id="hashChart" class="bar-chart"></div></div></div>
    </section>`:''}

    ${has(ch.timing)?`
    <section id="timing" data-label="Timing">
      ${sectionHead('Timing e finestre di pubblicazione','')}
      <div id="timingGrid" class="grid three"></div>
    </section>`:''}

    ${has(ch.community)?`
    <section id="community" data-label="Community">
      ${sectionHead('Community management','Attivita\' di gestione community nel periodo.')}
      <div class="grid four" id="communityGrid"></div>
    </section>`:''}

    ${roadmapHas?`
    <section id="roadmap" data-label="Roadmap">
      ${sectionHead('Roadmap operativa','')}
      <div class="card"><div class="tabs" id="roadTabs"></div><div id="roadPanels"></div></div>
    </section>`:''}

    ${has(N.conclusioni)?`
    <section id="conclusioni" data-label="Conclusioni">
      ${sectionHead('Conclusioni','')}
      <div class="grid two">
        <div class="card callout"><h3>Lettura conclusiva</h3>${(N.conclusioni.lettura||[]).map(p=>`<p style="margin-top:8px">${p}</p>`).join('')}</div>
        <div class="card"><h3>Direzione consigliata</h3><div class="metric-list">${(N.conclusioni.direzione||[]).map((d,i)=>`<div class="metric-row"><div><strong>${d.title}</strong><span>${d.desc}</span></div><div class="number">0${i+1}</div></div>`).join('')}</div></div>
      </div>
    </section>`:''}
    `;
  },
  linkedin: (ch) => {
    const N = ch.narrative || {};
    const audHas = ch.audience && Object.values(ch.audience).some(v => v && v.length);
    const visAudHas = ch.visitor_audience && Object.values(ch.visitor_audience).some(v => v && v.length);
    return `
    <section id="overview" data-label="Panoramica" class="hero">
      <div class="eyebrow">${DATA.meta.brand || ''}</div>
      <h2>Report ${ch.label}</h2>
      <p>${N.hero || (DATA.meta.period ? 'Periodo: ' + DATA.meta.period : '')}</p>
    </section>
    ${considerazioniHTML(N)}
    <section id="kpi" data-label="KPI">
      ${sectionHead('Dashboard KPI','Vista sintetica del periodo. Clicca una card per leggere l’interpretazione.')}
      <div id="kpiGrid" class="grid kpis"></div>
      <div id="kpiInsight" class="card insight-panel" style="margin-top:18px"></div>
    </section>
    ${has(ch.follower_growth) || has(ch.engagement_breakdown) ? `
    <section id="attivita" data-label="Attività">
      ${sectionHead('Crescita e interazioni','Nuovi follower per tipologia e interazioni generate dai contenuti.')}
      <div class="grid two">
        <div class="card"><h3>Nuovi follower per tipologia</h3><div id="liGrowth" class="bar-chart"></div></div>
        <div class="card"><h3>Interazioni sui contenuti</h3><div id="liEng" class="bar-chart"></div></div>
      </div>
    </section>`:''}
    ${has(ch.top_post) ? `
    <section id="contenuti" data-label="Contenuti">
      ${sectionHead('Post migliori','I post con più impressioni nel periodo.')}
      <div id="liPostCards" class="grid three"></div>
      <div class="card" style="margin-top:18px"><h3>Tabella post</h3><div class="table-wrap"><table id="liPostTable"><thead><tr><th>Data</th><th>Tema</th><th>Impressioni</th><th>Clic</th><th>CTR</th><th>Commenti</th></tr></thead><tbody></tbody></table></div></div>
    </section>`:''}
    ${audHas ? `
    <section id="audience" data-label="Audience">
      ${sectionHead('Audience dei follower','Chi sono i follower per funzione, anzianità, settore, dimensione azienda e città.')}
      <div class="grid two">
        <div class="card"><h3>Funzione lavorativa</h3><div id="liFunzione" class="bar-chart"></div></div>
        <div class="card"><h3>Anzianità</h3><div id="liAnzianita" class="bar-chart"></div></div>
      </div>
      <div class="grid two" style="margin-top:18px">
        <div class="card"><h3>Settore</h3><div id="liSettore" class="bar-chart"></div></div>
        <div class="card"><h3>Dimensione azienda</h3><div id="liDimensioni" class="bar-chart"></div></div>
      </div>
      <div class="grid two" style="margin-top:18px">
        <div class="card"><h3>Città</h3><div id="liLocalita" class="bar-chart"></div></div>
      </div>
    </section>`:''}
    ${has(ch.visitors_kpis) ? `
    <section id="visite" data-label="Visite pagina">
      ${sectionHead('Visite alla pagina','Visualizzazioni e visitatori unici della pagina nel periodo.')}
      <div class="grid two" id="liVisitorsKpi"></div>
      ${visAudHas ? `<div class="grid two" style="margin-top:18px"><div class="card"><h3>Visitatori per funzione</h3><div id="liVisFunzione" class="bar-chart"></div></div><div class="card"><h3>Visitatori per settore</h3><div id="liVisSettore" class="bar-chart"></div></div></div>`:''}
    </section>`:''}
    ${conclusioniHTML(N)}
    `;
  },
};

// ---------- wiring per tipo (usa gli ID montati nel canale attivo) ----------
const WIRE = {
  instagram: (ch) => {
    wireKpis(ch);
    // Split
    const splitButtons=document.getElementById('splitButtons');
    if(splitButtons && ch.split){ const labels={views:'Views',engagement:'Engagement',reach:'Reach media'};
      Object.keys(ch.split).forEach((key,i)=>{ const b=document.createElement('button'); b.className='btn'+(i===0?' active':''); b.textContent=labels[key]||key; b.dataset.key=key; splitButtons.appendChild(b); });
      const draw=(key)=>{ splitButtons.querySelectorAll('.btn').forEach(b=>b.classList.toggle('active',b.dataset.key===key)); const fc=key==='views'?'orange':key==='engagement'?'':'teal'; barChart(document.getElementById('splitChart'),ch.split[key],{fillClass:fc}); };
      splitButtons.addEventListener('click',e=>{ if(e.target.dataset.key) draw(e.target.dataset.key); }); draw(Object.keys(ch.split)[0]); }
    // Rate table
    const rateBody=document.querySelector('#rateTable tbody');
    if(rateBody && ch.rates) rateBody.innerHTML=ch.rates.map(r=>`<tr><td><strong>${r.metric}</strong></td><td>${r.organic}</td><td>${r.paid}</td><td><strong>${r.total}</strong></td><td>${r.insight||''}</td></tr>`).join('');
    // Engagement breakdown
    if(ch.engagement_breakdown) barChart(document.getElementById('engagementChart'), ch.engagement_breakdown.map(e=>({label:e.label,value:e.total,display:`${e.total} · ${e.variation}`})),{fillClass:'orange'});
    // Audience
    if(ch.audience_growth) barChart(document.getElementById('growthChart'), ch.audience_growth.map(x=>({label:x.label,value:x.value})),{fillClass:'teal'});
    const geoEl=document.getElementById('geoChart');
    if(geoEl){ if(has(ch.geo)) barChart(geoEl, ch.geo.map(x=>({label:x.city,value:x.followers})),{}); else document.getElementById('geoNote').innerHTML='<p class="empty-note">Dato non disponibile dal file (nel PDF e\' solo un grafico).</p>'; }
    const ap=document.getElementById('audienceProfile');
    if(ap){ const rows=(ch.audience_profile||[]); ap.innerHTML = rows.length? rows.map(r=>`<div class="metric-row"><div><strong>${r.label}</strong><span>${r.desc||''}</span></div><div class="number">${r.value}</div></div>`).join('') : '<p class="empty-note">Profilo demografico non disponibile dal file (solo grafico).</p>'; }
    // Publishing mix donut + format chart
    if(ch.publishing_mix){ const colors=['var(--pink)','var(--purple)','var(--orange)','var(--teal)','#b7afc0'];
      const tot=ch.publishing_mix.reduce((a,m)=>a+(m.posts||0),0); let acc=0; const stops=[];
      ch.publishing_mix.forEach((m,i)=>{ const deg=tot?(m.posts/tot)*360:0; stops.push(`${colors[i%colors.length]} ${acc}deg ${acc+deg}deg`); acc+=deg; });
      const donut=document.getElementById('mixDonut'); if(donut){ donut.style.background=`conic-gradient(${stops.join(',')||'#e7e7e7 0 360deg'})`; document.getElementById('mixTotal').textContent=tot; }
      const ml=document.getElementById('mixLegend'); if(ml) ml.innerHTML=ch.publishing_mix.map((m,i)=>`<div class="legend-item"><span style="display:flex;gap:8px"><i class="dot" style="background:${colors[i%colors.length]}"></i><span><strong>${m.format}</strong><br><small class="tiny">${m.share}% · ${m.variation}</small></span></span><b>${m.posts}</b></div>`).join('');
      barChart(document.getElementById('formatEngagementChart'), ch.publishing_mix.map(m=>({label:m.format,value:m.avg_engagement,display:`${m.avg_engagement} avg · ${m.posts} post`})),{fillClass:'teal',max:8}); }
    // Content cards + table
    if(ch.top_content){ let currentFilter='Tutti', sortState={key:'views',dir:'desc'};
      const filters=['Tutti',...new Set(ch.top_content.map(c=>c.type))];
      const cf=document.getElementById('contentFilters'); cf.innerHTML=filters.map((f,i)=>`<button class="btn ${i===0?'active':''}" data-filter="${f}">${f}</button>`).join('');
      const filtered=()=>ch.top_content.filter(c=>currentFilter==='Tutti'||c.type===currentFilter);
      const drawCards=()=>{ document.getElementById('contentCards').innerHTML=filtered().map(c=>`<div class="card content-card"><div class="content-top"><div><p class="content-title">${c.topic}</p><p class="tiny">${c.date} · ${c.time}</p></div><span class="tag ${tagClass(c.type)}">${c.type}</span></div><p class="content-desc">${c.description}</p><div class="mini-grid"><div class="mini-stat"><small>Views</small><strong>${fmt(c.views)}</strong></div><div class="mini-stat"><small>Reach</small><strong>${fmt(c.reach)}</strong></div><div class="mini-stat"><small>Eng.</small><strong>${fmt(c.engagement)}</strong></div></div><div class="pill-row"><span class="pill purple">ER view ${c.er_view}%</span><span class="pill teal">ER reach ${c.er_reach}%</span>${c.saved!=null?`<span class="pill pink">Saved ${c.saved}</span>`:(c.clicks!=null?`<span class="pill pink">Clic ${c.clicks}</span>`:'')}</div>${c.insight?`<p><strong>Insight:</strong> ${c.insight}</p>`:''}</div>`).join(''); };
      const drawTable=()=>{ const rows=[...filtered()].sort((a,b)=>{ let av=a[sortState.key],bv=b[sortState.key]; if(sortState.key==='date'){av=a.date.split('/').reverse().join('');bv=b.date.split('/').reverse().join('');} if(typeof av==='string') return sortState.dir==='asc'?av.localeCompare(bv):bv.localeCompare(av); return sortState.dir==='asc'?av-bv:bv-av; });
        document.querySelector('#contentTable tbody').innerHTML=rows.map(c=>`<tr><td>${c.date}<br><span class="tiny">${c.time}</span></td><td><span class="tag ${tagClass(c.type)}">${c.type}</span></td><td><strong>${c.topic}</strong></td><td>${c.views}</td><td>${c.reach}</td><td>${c.engagement}</td><td><strong>${c.er_reach}%</strong></td><td>${c.insight||''}</td></tr>`).join(''); };
      cf.addEventListener('click',e=>{ if(!e.target.dataset.filter)return; currentFilter=e.target.dataset.filter; cf.querySelectorAll('.btn').forEach(b=>b.classList.toggle('active',b.dataset.filter===currentFilter)); drawCards(); drawTable(); });
      document.querySelectorAll('#contentTable th[data-sort]').forEach(th=>th.addEventListener('click',()=>{ const k=th.dataset.sort; sortState.dir=sortState.key===k&&sortState.dir==='desc'?'asc':'desc'; sortState.key=k; drawTable(); }));
      drawCards(); drawTable(); }
    if(has(ch.stories)) barChart(document.getElementById('storyChart'), ch.stories.map((s,i)=>({label:`Story ${i+1} · ${s.date}`,value:s.views,display:`${s.views} views · reach ${s.reach}`})),{fillClass:'orange'});
    // Hashtags
    if(has(ch.hashtags)) barChart(document.getElementById('hashChart'), ch.hashtags.map(h=>({label:h.tag,value:h.value,display:`${h.value} interazioni`})),{});
    // Timing
    const tg=document.getElementById('timingGrid'); if(tg && has(ch.timing)) tg.innerHTML=ch.timing.map(t=>`<div class="card"><b>${t.label}</b><div class="number" style="font-size:20px;margin:6px 0">${t.slot}</div><span class="pill purple">${t.value}</span><p style="margin-top:10px">${t.note||''}</p></div>`).join('');
    // Community
    const cg=document.getElementById('communityGrid'); if(cg && has(ch.community)) cg.innerHTML=ch.community.map(c=>`<div class="card"><span class="tiny">${c.label}</span><div class="number" style="font-size:34px;margin:8px 0">${c.value}</div>${makeDelta(c.variation)}</div>`).join('');
    // Roadmap
    const rt=document.getElementById('roadTabs'), rp=document.getElementById('roadPanels');
    if(rt && rp && ch.roadmap){ const labels={continuare:'Continuare',potenziare:'Potenziare',correggere:'Correggere',testare:'Testare'};
      Object.keys(ch.roadmap).filter(k=>ch.roadmap[k]&&ch.roadmap[k].length).forEach((key,i)=>{ rt.insertAdjacentHTML('beforeend',`<button class="btn ${i===0?'active':''}" data-tab="${key}">${labels[key]||key}</button>`); rp.insertAdjacentHTML('beforeend',`<div class="tab-panel ${i===0?'active':''}" id="panel-${key}"><div class="road-list">${ch.roadmap[key].map((x,j)=>`<div class="road-item"><strong>${j+1}. ${labels[key]||key}</strong><span>${x}</span></div>`).join('')}</div></div>`); });
      rt.addEventListener('click',e=>{ if(!e.target.dataset.tab)return; const k=e.target.dataset.tab; rt.querySelectorAll('.btn').forEach(b=>b.classList.toggle('active',b.dataset.tab===k)); rp.querySelectorAll('.tab-panel').forEach(p=>p.classList.toggle('active',p.id==='panel-'+k)); }); }
  },
  linkedin: (ch) => {
    wireKpis(ch);
    const drawDim=(id,rows,fill)=>{ const el=byId(id); if(el&&rows&&rows.length) barChart(el, rows.map(r=>({label:r.label,value:r.value})),{fillClass:fill}); };
    if(has(ch.follower_growth)) barChart(byId('liGrowth'), ch.follower_growth.map(x=>({label:x.label,value:x.value})),{fillClass:'teal'});
    if(has(ch.engagement_breakdown)) barChart(byId('liEng'), ch.engagement_breakdown.map(e=>({label:e.label,value:e.total})),{fillClass:'orange'});
    if(has(ch.top_post)){
      const cards=byId('liPostCards'); if(cards) cards.innerHTML=ch.top_post.map(p=>`<div class="card content-card"><div class="content-top"><div><p class="content-title">${p.topic}</p><p class="tiny">${p.date}</p></div><span class="tag">${p.type||'Post'}</span></div><p class="content-desc">${p.description}</p><div class="mini-grid"><div class="mini-stat"><small>Impressioni</small><strong>${fmt(p.impressions)}</strong></div><div class="mini-stat"><small>Clic</small><strong>${fmt(p.clicks)}</strong></div><div class="mini-stat"><small>Commenti</small><strong>${fmt(p.comments)}</strong></div></div></div>`).join('');
      const tb=document.querySelector('#liPostTable tbody'); if(tb) tb.innerHTML=ch.top_post.map(p=>`<tr><td>${p.date}</td><td><strong>${p.topic}</strong></td><td>${fmt(p.impressions)}</td><td>${fmt(p.clicks)}</td><td>${p.ctr!==''&&p.ctr!==undefined?p.ctr+'%':'—'}</td><td>${fmt(p.comments)}</td></tr>`).join('');
    }
    const A=ch.audience||{};
    drawDim('liFunzione',A.funzione,''); drawDim('liAnzianita',A.anzianita,'teal'); drawDim('liSettore',A.settore,'orange'); drawDim('liDimensioni',A.dimensioni,''); drawDim('liLocalita',A.localita,'teal');
    if(has(ch.visitors_kpis)){ const vk=byId('liVisitorsKpi'); if(vk) vk.innerHTML=ch.visitors_kpis.map(k=>`<div class="card"><span class="tiny">${k.label}</span><div class="number" style="font-size:34px;margin:8px 0">${k.value}</div></div>`).join(''); }
    const VA=ch.visitor_audience||{}; drawDim('liVisFunzione',VA.funzione,''); drawDim('liVisSettore',VA.settore,'orange');
  },
};

// ---------- shell: tab, sidebar, scrollspy ----------
const main=document.getElementById('main'), sideNav=document.getElementById('sideNav'),
      mobileNav=document.getElementById('mobileNav'), tabbar=document.getElementById('tabbar');
document.getElementById('repBrand').textContent=DATA.meta.brand||'';
document.getElementById('repPeriod').textContent=DATA.meta.period||'';
document.getElementById('sideNote').textContent=DATA.meta.period||'';
document.title=(DATA.meta.brand||'Report')+' · Report social';

let spyObserver=null;
function buildSideNav(){
  const secs=[...main.querySelectorAll('section[data-label]')];
  sideNav.innerHTML=secs.map(s=>`<a href="#${s.id}">${s.dataset.label}</a>`).join('');
  mobileNav.innerHTML=secs.map(s=>`<option value="#${s.id}">${s.dataset.label}</option>`).join('');
  const links=[...sideNav.querySelectorAll('a')];
  if(spyObserver) spyObserver.disconnect();
  spyObserver=new IntersectionObserver(entries=>{ entries.forEach(en=>{ if(en.isIntersecting){ links.forEach(a=>a.classList.toggle('active',a.getAttribute('href')==='#'+en.target.id)); mobileNav.value='#'+en.target.id; } }); },{rootMargin:'-35% 0px -55% 0px'});
  secs.forEach(s=>spyObserver.observe(s));
}
mobileNav.addEventListener('change',e=>{ const t=document.querySelector(e.target.value); if(t) t.scrollIntoView({behavior:'smooth'}); });

function activate(idx){
  const ch=DATA.channels[idx]; D=ch;
  tabbar.querySelectorAll('.tab').forEach((b,i)=>b.classList.toggle('active',i===idx));
  main.innerHTML=(SECTION_HTML[ch.type]||SECTION_HTML.instagram)(ch);
  (WIRE[ch.type]||WIRE.instagram)(ch);  // Facebook e altri canali social riusano il render Instagram
  buildSideNav();
  main.scrollTop=0; window.scrollTo({top:0});
}
tabbar.innerHTML=DATA.channels.map((ch,i)=>`<button class="tab" data-idx="${i}">${ch.label}</button>`).join('');
tabbar.addEventListener('click',e=>{ if(e.target.dataset.idx!==undefined) activate(+e.target.dataset.idx); });
if(DATA.channels.length) activate(0);
</script>
</body>
</html>
"""


def build():
    with open(SRC, "r", encoding="utf-8") as f:
        src = f.read()
    head = src[: src.index("</style>") + len("</style>")]
    out = head + "\n" + EXTRA_CSS + "\n" + BODY_AND_SCRIPT
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(out)
    placeholders = [p for p in ["{{DATA}}", "{{PRIMARY}}", "{{SECONDARY}}", "{{DARK}}", "{{LOGO}}", "{{TITLE}}"] if p in out]
    print(f"scritto {OUT} ({len(out)} char)")
    print("segnaposto:", ", ".join(placeholders))


if __name__ == "__main__":
    build()
