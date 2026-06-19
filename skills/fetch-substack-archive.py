#!/usr/bin/env python3
"""fetch-substack-archive — download a whole Substack publication's back-catalogue
as clean, self-contained Markdown.

Engine for the /fetch-substack-archive skill. Works for ANY Substack publication
(public posts). It does NOT scrape rendered HTML pages; it uses Substack's own
JSON API, which is far cleaner and more reliable:

  1. Enumerate every post via the archive API
       GET <base>/api/v1/archive?sort=new&limit=50&offset=N
     -> post metadata (post_date, audience, title, slug, canonical_url).
     Quirk handled: offset=0 caps the page at ~23 items even with limit=50; later
     offsets return a full 50. So we paginate ADAPTIVELY (offset += items returned)
     and stop only when a page comes back empty -- never break on a short page.

  2. Fetch each post body via the per-post API
       GET <base>/api/v1/posts/<slug>
     -> `body_html` is the ARTICLE BODY ONLY: no site header, no like/share counts,
     no comments, no subscribe footer. Convert that HTML -> Markdown (markdownify).

  3. Strip Substack's inline "Subscribe for free" widgets (and share/comment buttons)
     by dropping any HTML element subtree whose class matches a blocked token, using
     a stdlib html.parser subclass (robust where nested-div regex is not).

  4. Images: skip the cover/thumbnail (matched by the underlying Substack S3 image
     UUID vs the post's cover_image); keep any genuine in-content image -- download
     it and rewrite its src to a relative images/<file> path. An article with kept
     images becomes a folder (<name>/article.md + images/); image-free articles stay
     flat <name>.md.

  5. Provenance: every file gets YAML frontmatter (source_url, title, subtitle,
     author, post_date, retrieved, engine) plus a visible H1 + Source line.

Resumable + rate-limit-safe: a per-output _done.json slug ledger means re-running
never re-fetches completed work and picks up only NEW posts; get_json backs off
exponentially on HTTP 429.

Dependencies: markdownify (pip). Pure-Python otherwise (stdlib urllib/html.parser).

Usage:
  python fetch-substack-archive.py <publication> [options]

  <publication>   Substack subdomain ("victorfitfleet"), full URL
                  ("https://victorfitfleet.substack.com"), an /archive URL, or a
                  custom domain that fronts a Substack.

Options:
  --out DIR           Output/staging dir (default: ./<subdomain>-archive)
  --prefix TAG        Filename prefix to tag the author/source, e.g. "victor-article-"
                      (recommended: keeps sources identifiable when mixed with others)
  --author NAME       Author for frontmatter (default: auto-detected from byline)
  --no-date           Do NOT put YYYY-MM-DD in the filename (default: include it)
  --always-folder     Every post gets its own folder (default: flat .md, folder only
                      when a post has kept in-content images)
  --delay SECS        Base politeness delay between posts (default: 1.2)
  --limit N           Only the newest N posts (for a quick test run)
  --list-only         Enumerate + write _manifest.json, download nothing
  --force             Re-download even posts already in the _done.json ledger
"""
import argparse, json, os, re, sys, time, datetime
import urllib.request, urllib.parse, urllib.error
from html.parser import HTMLParser

try:
    from markdownify import markdownify as md
except ImportError:
    sys.exit("markdownify is required: pip install markdownify")

UA = {"User-Agent": "Mozilla/5.0"}
ENGINE = "substack-api/v1 + markdownify"
BLOCK_CLASS_TOKENS = ("subscription-widget", "subscribe-widget", "button-wrapper",
                      "subscribe-button", "share-button", "comment-button")


# ---------- HTTP ----------
def get_json(url, retries=6):
    delay = 5.0
    for attempt in range(retries):
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=45))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                time.sleep(delay); delay = min(delay * 2, 90); continue
            raise

def download(url, dest):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, \
         open(dest, "wb") as f:
        f.write(r.read())


# ---------- helpers ----------
def resolve_base(pub):
    """Accept subdomain / full URL / archive URL / custom domain -> scheme+host base."""
    pub = pub.strip().rstrip("/")
    if "://" in pub:
        u = urllib.parse.urlparse(pub)
        return f"{u.scheme}://{u.netloc}"
    if "." in pub:                      # bare host like example.com or sub.substack.com
        return "https://" + pub
    return f"https://{pub}.substack.com"  # bare subdomain

def subdomain_of(base):
    host = urllib.parse.urlparse(base).netloc
    return host.split(".")[0]

def slugify(s, maxlen=70):
    s = (s or "").lower().replace("’", "").replace("'", "").replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0]
    return s.strip("-") or "untitled"

def s3_uuid(url):
    m = re.search(r"images%2F([0-9a-f-]{36})", url) or re.search(r"images/([0-9a-f-]{36})", url)
    return m.group(1) if m else None

def real_src(url):
    m = re.search(r"/image/fetch/[^/]+/(https?%3A%2F%2F.+)$", url)
    return urllib.parse.unquote(m.group(1)) if m else url

def yaml_escape(s):
    return '"' + (s or "").replace('\\', '\\\\').replace('"', '\\"') + '"'

def byline(post):
    names = [b.get("name") for b in (post.get("publishedBylines") or []) if b.get("name")]
    return " & ".join(names) if names else ""


# ---------- widget stripper ----------
class _WidgetStripper(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out = []; self.skip_depth = 0; self.stack = []
    def _blocked(self, attrs):
        cls = dict(attrs).get("class", "") or ""
        return any(tok in cls for tok in BLOCK_CLASS_TOKENS)
    def handle_starttag(self, tag, attrs):
        if self.skip_depth:
            self.skip_depth += 1; self.stack.append(tag); return
        if self._blocked(attrs):
            self.skip_depth = 1; self.stack.append(tag); return
        self.stack.append(tag); self.out.append(self.get_starttag_text())
    def handle_startendtag(self, tag, attrs):
        if self.skip_depth or self._blocked(attrs): return
        self.out.append(self.get_starttag_text())
    def handle_endtag(self, tag):
        if self.stack: self.stack.pop()
        if self.skip_depth: self.skip_depth -= 1; return
        self.out.append(f"</{tag}>")
    def handle_data(self, d):
        if not self.skip_depth: self.out.append(d)
    def handle_entityref(self, n):
        if not self.skip_depth: self.out.append(f"&{n};")
    def handle_charref(self, n):
        if not self.skip_depth: self.out.append(f"&#{n};")

def strip_widgets(html):
    p = _WidgetStripper(); p.feed(html); p.close()
    return "".join(p.out)


# ---------- enumerate ----------
def enumerate_archive(base, delay=0.4):
    items, off, url = [], 0, base + "/api/v1/archive?sort=new&limit=50&offset="
    while True:
        d = get_json(url + str(off))
        if not d: break
        items += d; off += len(d)
        if off > 5000: break          # safety
        time.sleep(delay)
    seen, uniq = set(), []
    for p in items:
        if p.get("id") in seen: continue
        seen.add(p.get("id")); uniq.append(p)
    return sorted(uniq, key=lambda x: x.get("post_date", ""))


# ---------- one post ----------
def process(base, entry, out, prefix, author_override, want_date, always_folder):
    slug = entry["slug"]; date = (entry.get("post_date") or entry.get("date") or "")[:10]
    post = get_json(f"{base}/api/v1/posts/{urllib.parse.quote(slug)}")
    body = strip_widgets(post.get("body_html") or "")
    title = post.get("title") or entry.get("title") or slug
    subtitle = post.get("subtitle") or ""
    url = post.get("canonical_url") or entry.get("canonical_url")
    author = author_override or byline(post) or subdomain_of(base)
    audience = post.get("audience")
    cover = post.get("cover_image") or ""
    cover_id = s3_uuid(cover) if cover else None

    # classify images
    kept = []
    for src in re.findall(r'<img[^>]+?src="([^"]+)"', body):
        uid = s3_uuid(src)
        if (cover_id and uid == cover_id) or (cover and src == cover):
            continue
        kept.append((src, real_src(src), uid))

    # drop cover img tags from the html so they don't pollute markdown
    if cover_id or cover:
        def drop(m):
            t = m.group(0); s = re.search(r'src="([^"]+)"', t)
            if s and ((cover_id and s3_uuid(s.group(1)) == cover_id) or s.group(1) == cover):
                return ""
            return t
        body = re.sub(r'<img[^>]+?>', drop, body)
        body = re.sub(r'<figure[^>]*>\s*</figure>', '', body)

    datepart = f"{date}-" if (want_date and date) else ""
    base_name = f"{prefix}{datepart}{slugify(title)}"

    img_jobs = []
    if kept or always_folder:
        outdir = os.path.join(out, base_name)
        os.makedirs(outdir, exist_ok=True)
        mdpath = os.path.join(outdir, "article.md")
        if kept:
            os.makedirs(os.path.join(outdir, "images"), exist_ok=True)
            for i, (orig, realu, uid) in enumerate(kept, 1):
                ext = os.path.splitext(urllib.parse.urlparse(realu).path)[1].lower()
                if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"): ext = ".png"
                fn = f"img-{i:02d}{('-'+uid[:8]) if uid else ''}{ext}"
                body = body.replace(orig, f"images/{fn}")
                img_jobs.append((realu, os.path.join(outdir, "images", fn)))
    else:
        mdpath = os.path.join(out, base_name + ".md")

    markdown = re.sub(r"\n{3,}", "\n\n",
                      md(body, heading_style="ATX", strip=["script", "style"]).strip())

    retrieved = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    fm = ["---", f"source_url: {url}", f"title: {yaml_escape(title)}"]
    if subtitle: fm.append(f"subtitle: {yaml_escape(subtitle)}")
    fm += [f"author: {yaml_escape(author)}", f"post_date: {date}"]
    if audience and audience != "everyone":
        fm.append(f"audience: {audience}   # NOTE: non-public — body may be a preview only")
    fm += [f"retrieved: {retrieved}", f"engine: {ENGINE}", "---", ""]
    header = f"# {title}\n\n" + (f"*{subtitle}*\n\n" if subtitle else "") + f"Source: {url}\n\n"
    with open(mdpath, "w", encoding="utf-8") as f:
        f.write("\n".join(fm) + header + markdown + "\n")

    for realu, dest in img_jobs:
        try: download(realu, dest)
        except Exception as e: print(f"   ! image failed {realu[:60]}: {e}")

    return {"path": os.path.relpath(mdpath, out), "images": len(img_jobs),
            "audience": audience}


# ---------- ledger ----------
def load_done(path):
    try: return set(json.load(open(path, encoding="utf-8")))
    except Exception: return set()

def save_done(path, done):
    d = os.path.dirname(os.path.abspath(path))
    if d: os.makedirs(d, exist_ok=True)
    json.dump(sorted(done), open(path, "w", encoding="utf-8"), indent=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("publication")
    ap.add_argument("--out"); ap.add_argument("--prefix", default="")
    ap.add_argument("--author"); ap.add_argument("--no-date", dest="date", action="store_false")
    ap.add_argument("--always-folder", action="store_true")
    ap.add_argument("--free-only", action="store_true",
                    help="skip paywalled posts entirely (audience != everyone)")
    ap.add_argument("--ledger", help="resume-ledger path (default <out>/_done.json); point at a "
                                     "durable location for an ongoing watch so it survives staging cleanup")
    ap.add_argument("--manifest", help="manifest output path (default <out>/_manifest.json)")
    ap.add_argument("--delay", type=float, default=1.2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    base = resolve_base(a.publication)
    out = a.out or os.path.abspath(f"{subdomain_of(base)}-archive")
    os.makedirs(out, exist_ok=True)
    ledger_path = a.ledger or os.path.join(out, "_done.json")
    manifest_path = a.manifest or os.path.join(out, "_manifest.json")
    print(f"publication: {base}\noutput dir : {out}\nledger     : {ledger_path}")

    man = enumerate_archive(base)
    mdir = os.path.dirname(os.path.abspath(manifest_path))
    if mdir: os.makedirs(mdir, exist_ok=True)
    json.dump([{"date": (p.get("post_date") or "")[:10], "audience": p.get("audience"),
                "title": p.get("title"), "slug": p.get("slug"),
                "canonical_url": p.get("canonical_url")} for p in man],
              open(manifest_path, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    nonfree = [p for p in man if p.get("audience") != "everyone"]
    print(f"posts found: {len(man)}  ({(man[0].get('post_date') or '')[:10]} -> "
          f"{(man[-1].get('post_date') or '')[:10]})  non-public: {len(nonfree)}")
    print(f"manifest written: {manifest_path}  (last/newest = bottom)")
    if a.list_only:
        print("RESULT_SUMMARY:" + json.dumps({"publication": base, "found": len(man),
              "nonfree": len(nonfree), "downloaded": 0, "list_only": True}))
        return

    work = man[-a.limit:] if a.limit else man
    if a.free_only:
        work = [e for e in work if e.get("audience") == "everyone"]
    done = set() if a.force else load_done(ledger_path)
    ok = fail = skipped = imgs = 0; new_items = []
    for i, e in enumerate(work, 1):
        if e["slug"] in done: skipped += 1; continue
        try:
            r = process(base, e, out, a.prefix, a.author, a.date, a.always_folder)
            done.add(e["slug"]); save_done(ledger_path, done); ok += 1
            if r["images"]: imgs += 1
            new_items.append({"date": (e.get("post_date") or "")[:10],
                              "title": e.get("title"), "path": r["path"]})
            flag = f"  [{r['images']} img]" if r["images"] else ""
            warn = "  <PREVIEW?>" if (r["audience"] and r["audience"] != "everyone") else ""
            print(f"[{i:>4}/{len(work)}] {r['path']}{flag}{warn}")
        except Exception as ex:
            fail += 1; print(f"[{i:>4}/{len(work)}] FAIL {e['slug']}: {ex}")
        time.sleep(a.delay)

    print(f"\n==== SUMMARY ====\ndownloaded: {ok}  | with images: {imgs}  | "
          f"skipped(done): {skipped}  | failed: {fail}")
    if fail:
        print("Re-run the same command to retry failures (resumable via the ledger).")
    print("RESULT_SUMMARY:" + json.dumps({"publication": base, "found": len(man),
          "nonfree": len(nonfree), "downloaded": ok, "with_images": imgs,
          "skipped": skipped, "failed": fail, "free_only": a.free_only, "new": new_items}))


if __name__ == "__main__":
    main()
