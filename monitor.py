"""Monitor regulatorio de gasolineras (Profeco, CNE, ASEA).
Recolecta fuentes, clasifica con Claude y escribe docs/items.json."""
import os, re, json, hashlib, datetime as dt
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests, feedparser, anthropic
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "items.json")
CFG = json.load(open(os.path.join(ROOT, "sources.json")))
MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_NEW, BATCH = 60, 10
WINDOW = int(os.getenv("WINDOW_DAYS", "7"))      # solo noticias de los últimos N días
TZ = ZoneInfo("America/Mexico_City")
MESES = {m: n for n, m in enumerate("enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
def today(): return dt.datetime.now(TZ).date()
UA = {"User-Agent": "Mozilla/5.0 (monitor-gasolineras)"}
KEYS = re.compile(r"gasoliner|estaci[oó]n(es)? de servicio|expendio|petrol[ií]fer|"
                  r"combustible|NOM-|clausur|verificaci[oó]n|diésel|diesel", re.I)

DOF_KEYS = re.compile(r"petrol[ií]fer|estaci[oó]n(es)? de servicio|expendio|hidrocarbur|gasolin|di[eé]sel|NOM-\d+-(ASEA|SENER)|"
                      r"Agencia de Seguridad, Energ[ií]a|Comisi[oó]n Nacional de Energ[ií]a|Profeco|Procuradur[ií]a Federal del Consumidor|"
                      r"combustible|instrumentos de medici[oó]n", re.I)

SYSTEM = """Eres asesor regulatorio para gasolineras en México (Profeco, CNE, ASEA, SAT, Sener).
Recibes noticias/comunicados y devuelves SOLO un arreglo JSON, un objeto por elemento, en el mismo orden:
{"relevant":bool,"org":"Profeco|CNE|ASEA|Otro","level":"alto|medio|bajo",
 "title":"máx 110 caracteres","summary":"2 frases, sin inventar datos","action":"qué debe hacer un permisionario"}
Criterios: alto = clausuras, operativos, sanciones, plazos o nuevas obligaciones con fecha cercana,
suspensión/revocación de permisos. medio = nuevas normas, anteproyectos, cambios de trámite o formatos.
bajo = estadísticas, contexto de mercado. relevant=false si no afecta a operadores de estaciones de servicio.
relevant=false si el hecho principal no ocurrió en el año en curso o es una nota antigua republicada.
Usa solo lo que dice el texto; si falta un dato (fecha, monto), no lo inventes."""

def sid(link): return hashlib.sha1(link.encode()).hexdigest()[:12]

def from_rss(url):
    for e in feedparser.parse(url).entries[:25]:
        pp = e.get("published_parsed")
        d = dt.datetime(*pp[:6], tzinfo=dt.timezone.utc).astimezone(TZ).date() if pp else None
        yield {"title": e.get("title", ""), "link": e.get("link", ""), "date": d,
               "text": BeautifulSoup(e.get("summary", ""), "html.parser").get_text(" ")[:600]}

def from_html(url):
    try:
        r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
    except Exception as ex:
        print("HTML falló", url, ex); return
    for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
        t = a.get_text(" ", strip=True)
        if len(t) > 30:
            yield {"title": t, "link": urljoin(url, a["href"]), "date": None, "text": ""}

def from_dof():
    """Edición diaria del DOF (últimos WINDOW días): notas cuyo título coincide con el sector."""
    base = "https://www.dof.gob.mx/"
    for back in range(WINDOW + 1):
        d = today() - dt.timedelta(days=back)
        try:
            r = requests.get(f"{base}index_111.php?year={d.year}&month={d.month:02d}&day={d.day:02d}", headers=UA, timeout=30)
            r.raise_for_status()
        except Exception as ex:
            print("DOF falló", d, ex); continue
        for a in BeautifulSoup(r.text, "html.parser").find_all("a", href=True):
            t = a.get_text(" ", strip=True)
            if "nota_detalle" in a["href"] and len(t) > 20 and DOF_KEYS.search(t):
                link = urljoin(base, a["href"]); body = ""
                try: body = BeautifulSoup(requests.get(link, headers=UA, timeout=25).text, "html.parser").get_text(" ", strip=True)[:800]
                except Exception: pass
                yield {"title": t, "link": link, "date": d, "text": body, "pre": True}

def page_date(url):
    """Fecha de publicación de una página (meta, <time> o texto '12 de octubre de 2026')."""
    try:
        r = requests.get(url, headers=UA, timeout=25); r.raise_for_status()
    except Exception:
        return None
    s = BeautifulSoup(r.text, "html.parser")
    cands = [m.get("content") for m in s.find_all("meta") if m.get("property") in ("article:published_time", "og:published_time")
             or m.get("name") in ("date", "pubdate") or m.get("itemprop") == "datePublished"]
    cands += [t.get("datetime") for t in s.find_all("time") if t.get("datetime")]
    for c in cands:
        if c and re.match(r"\d{4}-\d{2}-\d{2}", c): return dt.date.fromisoformat(c[:10])
    m = re.search(r"(\d{1,2}) de (%s) (?:de|del) (\d{4})" % "|".join(MESES), s.get_text(" ")[:4000], re.I)
    return dt.date(int(m[3]), MESES[m[2].lower()], int(m[1])) if m else None

def classify(batch):
    client = anthropic.Anthropic()
    payload = [{"i": n, "titulo": b["title"], "texto": b["text"], "fecha": str(b["date"]), "fuente": b["link"]} for n, b in enumerate(batch)]
    msg = client.messages.create(model=MODEL, max_tokens=3000, system=SYSTEM,
                                 messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    raw = "".join(b.text for b in msg.content if b.type == "text")
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)

def main():
    db = json.load(open(OUT)) if os.path.exists(OUT) else {"items": []}
    seen = set(db.get("seen", [])) | {i["id"] for i in db["items"]}
    t0 = today(); min_d = t0 - dt.timedelta(days=WINDOW)
    cands, ids = [], set()
    for u in CFG["rss"]:
        try: cands += list(from_rss(u))
        except Exception as ex: print("RSS falló", u, ex)
    for u in CFG["html"]: cands += list(from_html(u))
    if CFG.get("dof"): cands += list(from_dof())
    new = []
    for c in cands:
        i = sid(c["link"])
        if c["link"] and i not in seen and i not in ids and (c.get("pre") or KEYS.search(c["title"] + " " + c["text"])):
            c["id"] = i; ids.add(i)
            if c["date"] is None and len(new) < MAX_NEW: c["date"] = page_date(c["link"])
            seen.add(i)                                   # no volver a evaluar
            d = c["date"]
            if d and d.year == t0.year and min_d <= d <= t0: new.append(c)   # solo año y ventana actuales
    new = new[:MAX_NEW]
    added = []
    for k in range(0, len(new), BATCH):
        b = new[k:k + BATCH]
        try: res = classify(b)
        except Exception as ex:
            print("Clasificación falló", ex)
            for c in b: seen.discard(c["id"])             # reintentar en la siguiente corrida
            continue
        for c, r in zip(b, res):
            if not r.get("relevant"): continue
            added.append({"id": c["id"], "date": c["date"].isoformat(), "org": r.get("org", "Otro"),
                          "level": r.get("level", "bajo"), "title": r.get("title", c["title"]),
                          "summary": r.get("summary", ""), "action": r.get("action", ""), "url": c["link"]})
    items = [i for i in added + db["items"] if i["date"][:4] == str(t0.year) and i["date"] >= min_d.isoformat()]
    json.dump({"updated": dt.datetime.now(dt.timezone.utc).isoformat(), "items": items, "seen": list(seen)[-20000:]},
              open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"{len(added)} nuevas relevantes de {len(new)} candidatas")
    hook = os.getenv("ALERT_WEBHOOK"); urgent = [i for i in added if i["level"] == "alto"]
    if hook and urgent:
        txt = "🔴 Alertas urgentes gasolineras:\n" + "\n".join(f"• [{i['org']}] {i['title']} {i['url']}" for i in urgent)
        requests.post(hook, json={"text": txt, "content": txt}, timeout=20)

if __name__ == "__main__":
    main()
