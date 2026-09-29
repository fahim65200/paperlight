#!/usr/bin/env python3
"""Paperlight thesis collector.

Visits open university repositories, collects thesis metadata (title, author,
year, link) and writes atlas/theses.json for the Thesis Search page.
Only metadata and links are stored; no PDFs are copied.
Standard library only, so it runs anywhere Python 3.9+ is installed.
"""
import json, os, re, sys, time, html, urllib.request, urllib.parse, urllib.robotparser
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONF = json.load(open(os.path.join(ROOT, "collector", "sources.json"), encoding="utf-8"))
OUT = os.path.join(ROOT, "atlas", "theses.json")
CURATED = os.path.join(ROOT, "atlas", "theses.js")
UA = "PaperlightThesisCollector/1.0 (open metadata for a free thesis search; links only)"
DELAY = float(CONF.get("delay_seconds", 1.0))
MAX_PAGES = int(CONF.get("max_pages_per_source", 400))
EXCLUDE = re.compile(CONF.get("exclude_title", "$^"), re.I)
THESIS_TYPE = re.compile(r"thesis|dissertation", re.I)
_robots = {}
_last = [0.0]

def log(*a):
    print(*a, flush=True)

def allowed(url):
    p = urllib.parse.urlparse(url)
    key = f"{p.scheme}://{p.netloc}"
    if key not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(key + "/robots.txt")
        try:
            rp.read()
        except Exception:
            rp = None
        _robots[key] = rp
    rp = _robots[key]
    return True if rp is None else rp.can_fetch(UA, url)

def get(url, accept="*/*", tries=3):
    if not allowed(url):
        raise PermissionError(f"robots.txt disallows {url}")
    wait = DELAY - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
            with urllib.request.urlopen(req, timeout=60) as r:
                _last[0] = time.time()
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except Exception as e:
            err = e
            time.sleep(2 * (i + 1))
    raise err

def year_of(s):
    m = re.search(r"(1[89]\d{2}|20\d{2})", s or "")
    return int(m.group(1)) if m else None

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

# ---------------- OAI-PMH ----------------
NS = {"o": "http://www.openarchives.org/OAI/2.0/", "dc": "http://purl.org/dc/elements/1.1/",
      "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/"}

def harvest_oai(src):
    base = src["oai"]
    url = f"{base}?verb=ListRecords&metadataPrefix=oai_dc"
    items, pages = [], 0
    while url and pages < MAX_PAGES:
        text = get(url, "text/xml")
        root = ET.fromstring(text.encode("utf-8"))
        err = root.find("o:error", NS)
        if err is not None:
            if err.get("code") == "noRecordsMatch":
                break
            raise RuntimeError(f"OAI error {err.get('code')}: {err.text}")
        for rec in root.iterfind(".//o:record", NS):
            h = rec.find("o:header", NS)
            if h is not None and h.get("status") == "deleted":
                continue
            md = rec.find(".//oai_dc:dc", NS)
            if md is None:
                continue
            f = lambda tag: [clean(e.text) for e in md.findall(f"dc:{tag}", NS) if e.text]
            links = [i for i in f("identifier") if i.startswith("http") and "/handle/" in i] or [i for i in f("identifier") if i.startswith("http")]
            items.append({"title": (f("title") or [""])[0], "authors": f("creator") or f("contributor")[:1],
                          "year": year_of(" ".join(f("date"))), "types": f("type"), "subjects": f("subject"),
                          "url": links[0] if links else None})
        pages += 1
        tok = root.find(".//o:resumptionToken", NS)
        url = f"{base}?verb=ListRecords&resumptionToken={urllib.parse.quote(tok.text.strip())}" if tok is not None and tok.text and tok.text.strip() else None
        log(f"    OAI page {pages}: {len(items)} records so far")
    return items

# ---------------- DSpace 7 REST ----------------
def harvest_dspace7(src):
    api = src["dspace7"].rstrip("/")
    ui = api.rsplit("/server", 1)[0]
    items, page, total_pages = [], 0, 1
    while page < total_pages and page < MAX_PAGES:
        data = json.loads(get(f"{api}/discover/search/objects?dsoType=ITEM&size=100&page={page}&sort=dc.date.issued,DESC", "application/json"))
        sr = data["_embedded"]["searchResult"]
        total_pages = sr.get("page", {}).get("totalPages", 1)
        for o in sr.get("_embedded", {}).get("objects", []):
            it = o["_embedded"]["indexableObject"]
            md = it.get("metadata", {})
            v = lambda k: [clean(x.get("value")) for x in md.get(k, [])]
            handle = it.get("handle")
            items.append({"title": clean(it.get("name")) or (v("dc.title") or [""])[0],
                          "authors": v("dc.contributor.author") or v("dc.creator"),
                          "year": year_of(" ".join(v("dc.date.issued"))), "types": v("dc.type"),
                          "subjects": v("dc.subject"),
                          "url": f"{ui}/handle/{handle}" if handle else f"{ui}/items/{it.get('uuid')}"})
        page += 1
        log(f"    DSpace 7 page {page}/{total_pages}: {len(items)} records so far")
    return items

# ---------------- DSpace XMLUI (HTML pages) ----------------
ITEM_LINK = re.compile(r'<a[^>]+href="([^"]*/handle/[^"/]+/\d+)"[^>]*>(.*?)</a>', re.S | re.I)

def parse_xmlui(page_html, base):
    out, seen = [], set()
    for m in ITEM_LINK.finditer(page_html):
        href, inner = m.group(1), m.group(2)
        title = clean(re.sub(r"<[^>]+>", " ", inner))
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        tail = page_html[m.end(): m.end() + 1500]
        nxt = ITEM_LINK.search(tail)
        if nxt:
            tail = tail[: nxt.start()]
        au = re.search(r'class="[^"]*author[^"]*"[^>]*>(.*?)</(?:span|div)>', tail, re.S | re.I)
        dt = re.search(r'class="date"[^>]*>(.*?)<', tail, re.S | re.I) or re.search(r'class="[^"]*\bdate\b[^"]*"[^>]*>([^<]*\d{4}[^<]*)<', tail, re.S | re.I)
        author = clean(re.sub(r"<[^>]+>", " ", au.group(1))) if au else ""
        yr = year_of(dt.group(1)) if dt else year_of(re.sub(r"<[^>]+>", " ", tail[:600]))
        url = urllib.parse.urljoin(base + "/", href)
        out.append({"title": title, "authors": [author] if author else [], "year": yr, "types": [], "subjects": [], "url": url})
    return out

def harvest_xmlui(src):
    base = src["xmlui"].rstrip("/")
    scopes = src.get("xmlui_scopes") or [{"path": c, "assume": True} for c in src.get("xmlui_collections") or []] or [{"path": ""}]
    items, seen = [], set()
    for sc in scopes:
        root = f"{base}/handle/{sc['path']}" if sc.get("path") else base
        extra = f"&filtertype=type&filter_relational_operator=contains&filter={urllib.parse.quote(sc['type'])}" if sc.get("type") else ""
        for page in range(1, MAX_PAGES + 1):
            url = f"{root}/discover?rpp=100&page={page}&sort_by=dc.date.issued_dt&order=desc{extra}"
            try:
                got = [i for i in parse_xmlui(get(url, "text/html"), base) if i["url"] not in seen]
            except Exception as e:
                log(f"    HTML scope {root} stopped: {e}")
                break
            if not got:
                break
            for i in got:
                seen.add(i["url"])
                if sc.get("type") or sc.get("assume"):
                    i["types"] = ["thesis (from repository filter)"]
            items += got
            log(f"    HTML page {page} of {root}{' [type=' + sc['type'] + ']' if sc.get('type') else ''}: {len(items)} records so far")
    return items

METHODS = {"oai": harvest_oai, "dspace7": harvest_dspace7, "xmlui": harvest_xmlui}

# ---------------- tagging ----------------
TOPICS = [("Flood", r"flood|inundation"), ("Cyclone", r"cyclone|storm surge"), ("Salinity", r"salin"),
          ("Arsenic", r"arsenic"), ("Drinking water", r"drinking water|water supply|safe water"),
          ("Groundwater", r"groundwater|aquifer"), ("Rivers & sediment", r"river|sediment|morpholog|erosion"),
          ("Coastal", r"coast|delta|sundarban|tidal"), ("Rainfall & temperature", r"rainfall|precipitation|monsoon|temperature"),
          ("Climate", r"climate"), ("Drought", r"drought"), ("Agriculture", r"agricultur|crop|farm|irrigat|rice"),
          ("Fisheries", r"fish|aquacult|shrimp"), ("Urban", r"urban|city|dhaka|chittagong|khulna city"),
          ("Health", r"health|disease|patient|hospital|nutrition"), ("Gender", r"gender|women"),
          ("Disaster management", r"disaster|hazard|resilien|vulnerab|risk reduction|early warning|emergency"),
          ("Energy", r"energy|solar|power|electric"), ("Economics", r"econom|poverty|income|market|price"),
          ("Education", r"education|school|student"), ("Transport", r"transport|traffic|road"),
          ("Housing", r"housing|building|homestead"), ("Land use", r"land use|land cover")]
METHODS_T = [("GIS", r"\bgis\b|geoinformat|geographic information"), ("Remote sensing", r"remote sensing|satellite|landsat|sentinel"),
             ("Modelling", r"model|simulat|wrf|hec-ras|mike"), ("Statistics", r"statistic|regression|correlation|trend|forecast"),
             ("Machine learning", r"machine learning|neural network|deep learning|\bai\b"), ("Case study", r"case study"),
             ("Survey", r"survey|questionnaire|household")]
FIELDS = [
 ("Disaster & climate", r"disaster|hazard|cyclone|flood|climate|resilien|vulnerab|drought|early warning|earthquake|landslide|emergency|fire safety"),
 ("Water & environment", r"water|river|salin|arsenic|groundwater|environment|sediment|wetland|ecosystem|pollut|waste|sanitation|biodiversity|forest|mangrove"),
 ("Computer science", r"comput|software|network|algorithm|machine learning|neural|deep learning|\bai\b|artificial intelligence|detect|extraction|security system|bangla document|speech|chatbot|data mining|blockchain|iot\b|internet of things|cyber|web\b|android|app\b|database|cloud|image processing|detection using|classification|recognition|nlp|natural language"),
 ("Health & pharmacy", r"health|medic|disease|patient|hospital|nutrition|pharma|drug|clinical|cancer|diabet|covid|maternal|nursing|antibiot|tuberculosis|depression|geriatric|anesthe|prevalence|elderly|pregnan|dengue|mental|psycholog"),
 ("Business & economics", r"bank|financ|marketing|customer|consumer|brand|business|compan|firm\b|firms|market|econom|poverty|income|investment|stock|employee|job satisfaction|management practice|human resource|\bhr\b|organization|organisation|sme|entrepreneur|retail|garment|rmg|supply chain|tax|internship report|profitab|loan|microfinance|insurance|telecom|trade|productivity|compensation|public sector|salary|export|import|gdp|inflation|remittance"),
 ("Architecture & planning", r"architect|design of|redesign|complex|centre|center|housing|homestead|urban|city|planning|residential|campus|museum|terminal|interior|landscape|revitaliz|rehabilitation of|space|building|shelter|pilgrim|shishu|memorial|resort|hub\b|market place|mosque"),
 ("Language & education", r"english|language|teach|learning|learner|classroom|student|school|education|literature|novel|poem|poetry|efl|esl|vocabulary|writing skill|speaking|reading|translation|curriculum|tertiary|nonfiction|fiction|narrative"),
 ("Law & governance", r"\blaw\b|legal|rights|court|justice|constitution|act\b|legislat|policy|governance|government|parliament|election|crime|police|human trafficking"),
 ("Media & social science", r"media|journalis|social|gender|women|child|youth|communit|migra|culture|religio|ngo|livelihood|refugee|rohingya|film|television|advertis"),
 ("Engineering", r"engineer|structur|concrete|mechanic|electric|power|material|textile|circuit|voltage|antenna|solar|energy|fuel|thermal|heat|fluid|steel|bridge|road|traffic|transport|vehicle|motor|robot|sensor|signal|wireless|communication system|semiconductor|optic|fabric|yarn|device|pile|ground improvement|geotechn|foundation"),
 ("Maths, stats & physics", r"lattice|ideal|theorem|equation|nearlattice|mathemat|numerical|runge|physic|quantum|magnetic|crystal|plasma|laser|statistic|regression|probabil|stochastic"),
 ("Biology & agriculture", r"agricult|crop|farm|rice|soil|plant|seed|fish|aquacult|shrimp|livestock|poultry|gene|microb|bacteri|enzyme|biotech|protein|food"),
]

def tag(text):
    t = text.lower()
    return ([n for n, p in TOPICS if re.search(p, t)], [n for n, p in METHODS_T if re.search(p, t)],
            next((n for n, p in FIELDS if re.search(p, t)), "Other"))

def norm_title(t):
    return re.sub(r"[^a-z0-9]", "", t.lower())[:120]

# ---------------- main ----------------
def load_curated():
    try:
        txt = open(CURATED, encoding="utf-8").read()
        return json.loads(txt[txt.index("["): txt.rindex("]") + 1])
    except Exception as e:
        log("  (could not read curated list:", e, ")")
        return []

def main():
    only = sys.argv[1:]
    report, collected = [], []
    for src in CONF["sources"]:
        if not src.get("enabled", True) or (only and src["id"] not in only):
            continue
        log(f"\n== {src['name']} ==")
        rows, used, errors = [], [], []
        for m in src.get("methods", []):
            if m not in METHODS or not src.get(m):
                continue
            try:
                log(f"  trying {m} ...")
                got = METHODS[m](src)
                if got:
                    have = {r["url"] for r in rows}
                    rows += [r for r in got if r.get("url") not in have]
                    used.append(m)
                    if not src.get("merge_methods"):
                        break
                else:
                    errors.append(f"{m}: no records")
            except Exception as e:
                errors.append(f"{m}: {type(e).__name__}: {str(e)[:160]}")
                log("   failed:", errors[-1])
        used = "+".join(used) or None
        kept = 0
        for r in rows or []:
            if not r.get("title") or not r.get("url") or EXCLUDE.search(r["title"]):
                continue
            is_thesis = any(THESIS_TYPE.search(t) for t in r.get("types", []))
            if not is_thesis and not (src.get("assume_thesis") and not r.get("types")):
                continue
            topics, methods, field = tag(" ".join([r["title"]] + r.get("subjects", [])))
            collected.append({"title": r["title"], "author": "; ".join(r["authors"][:3]) or "See repository",
                              "year": r["year"], "degree": "Not listed", "field": field, "institution": src["name"],
                              "uni": src["uni"], "url": r["url"], "topics": topics, "methods": methods, "auto": True})
            kept += 1
        report.append({"id": src["id"], "name": src["name"], "method": used, "fetched": len(rows or []), "kept": kept, "errors": errors})
        log(f"  -> {kept} theses kept (method: {used or 'none'})")

    curated = load_curated()
    seen, items = set(), []
    for it in curated + collected:  # curated first so hand-checked entries win
        k2 = norm_title(it["title"]) + str(it.get("year"))
        k1 = None if re.search(r"recent-submissions|/browse|/discover", it["url"]) else it["url"].split("?")[0]
        if (k1 and k1 in seen) or k2 in seen:
            continue
        seen.update([k for k in (k1, k2) if k])
        items.append(it)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "count": len(items),
           "curated": len(curated), "sources": report, "items": items}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    summary = ["## Thesis collector results", "", f"**Total in index: {len(items)}** ({len(curated)} hand-checked)", "",
               "| Source | Method | Fetched | Theses kept | Problems |", "|---|---|---|---|---|"]
    for r in report:
        summary.append(f"| {r['name']} | {r['method'] or 'failed'} | {r['fetched']} | {r['kept']} | {'; '.join(r['errors'])[:300] or '-'} |")
    text = "\n".join(summary)
    log("\n" + text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8").write(text + "\n")

if __name__ == "__main__":
    main()
