# Fetch Substack Archive — download a whole publication's back-catalogue as clean Markdown

Downloads **every public post** of a Substack publication into a staging folder as self-contained
Markdown — one `.md` per article, with provenance frontmatter (including the article URL), the
subscribe/comment/footer chrome stripped, and any genuine in-content images kept. Built for feeding
an author's full corpus into an LLM-wiki `raw/` layer, but it is a **general-purpose tool**: it
assigns no catalog IDs and knows nothing about any `raw/` folder.

The work is done by the companion engine **`fetch-substack-archive.py`** (same folder as this file).

---

## Why the JSON API, not page scraping (the reasoning baked in)

Substack exposes its own JSON API, and using it is the whole trick — it is far cleaner and more
reliable than scraping rendered HTML:

- **Enumerate** with `GET <base>/api/v1/archive?sort=new&limit=50&offset=N` → post metadata. A
  rendered `/archive` page is infinite-scroll and would need a headless browser; the API just
  paginates. **Quirk the engine handles:** `offset=0` caps the first page at ~23 items even with
  `limit=50`; later offsets return a full 50. So it paginates **adaptively** (`offset += items
  returned`) and stops only on an empty page — never breaks on a short page.
- **Extract** each post with `GET <base>/api/v1/posts/<slug>` → `body_html` is the **article body
  only**: no site header, no like/share counts, **no comments, no subscribe footer**. Scraping the
  page instead would force trimming all that chrome off every post (fragile, per-site). The engine
  converts `body_html` → Markdown with `markdownify`.

Everything else (widget stripping, image handling, resume, backoff) exists to turn that clean body
into a faithful, self-contained `.md`.

---

## STEP 1 — Resolve inputs

You need the **publication** — accept any of: a bare subdomain (`victorfitfleet`), a full URL
(`https://victorfitfleet.substack.com`), an `/archive` URL, or a custom domain that fronts a
Substack. If the user did not give one, ask and stop.

Capture from the request so you don't re-ask: the **filename prefix** (the author/source tag, e.g.
`victor-article-` — strongly recommended so sources stay identifiable when a folder mixes multiple
authors/categories), the **staging/output dir**, and any layout/date preferences.

## STEP 2 — Ensure the engine can run

The engine needs **markdownify** (`pip install markdownify` — pure Python, no pandoc). It is
otherwise stdlib. Use whichever Python launcher exists — `python`, `py -3`, or `python3`.

## STEP 3 — Recon first with `--list-only`

Before downloading anything, run once with `--list-only` to enumerate the archive and write
`<out>/_manifest.json` without fetching bodies:

```bash
python "~/.claude/skills/fetch-substack-archive.py" <publication> --out <DIR> --list-only
```

Report back the **post count, date range, and how many are non-public** (paywalled posts return a
preview body, not the full article — the engine tags those with `audience:` in frontmatter and a
`<PREVIEW?>` marker in the run log). This is also where you confirm the count against what the user
expects.

## STEP 4 — Run the download

```bash
python "~/.claude/skills/fetch-substack-archive.py" <publication> \
    --out <DIR> --prefix "<tag>-" [--author NAME] [--no-date] [--always-folder] [--delay 1.2] [--limit N]
```

| Option | Effect |
|--------|--------|
| `--out DIR` | staging/output dir (default `./<subdomain>-archive`) |
| `--prefix TAG` | filename prefix, e.g. `victor-article-` — keeps the source identifiable among mixed raw sources |
| `--author NAME` | author for frontmatter (default: **auto-detected from the post byline**) |
| `--no-date` | omit `YYYY-MM-DD` from filenames (default: **include it** — sorts chronologically and disambiguates same-day posts) |
| `--always-folder` | every post gets its own folder (default: flat `.md`, folder **only** when a post has kept in-content images) |
| `--free-only` | skip paywalled posts entirely (`audience != everyone`) — don't even fetch their previews |
| `--ledger PATH` | resume-ledger path (default `<out>/_done.json`). **Point at a durable location** (outside scratch staging) for an ongoing/scheduled watch, so the "what's been fetched" memory survives staging cleanup |
| `--manifest PATH` | manifest output path (default `<out>/_manifest.json`) |
| `--delay SECS` | base politeness delay between posts (default 1.2 — see rate-limit note) |
| `--limit N` | only the newest N posts (validation/test runs) |
| `--force` | re-download even posts already in the ledger |

The run ends with a machine-readable `RESULT_SUMMARY:{…}` JSON line (publication, found, nonfree,
downloaded, skipped, failed, and a `new` list of `{date,title,path}`) — parse that for automation
rather than scraping the per-post log lines.

**Filename:** `<prefix><YYYY-MM-DD->-<title-slug>.md`. **Layout default:** flat `.md` files; a post
with genuine in-content images becomes a folder (`<name>/article.md` + `images/`) so a folder
visually flags the graphic exception at a glance.

**Always do a `--limit 2` or `--limit 3` validation run first**, read one output file end-to-end to
confirm the body is clean and complete, then run the full archive.

## STEP 5 — Report

Parse the `==== SUMMARY ====` line. Tell the user: total downloaded, how many became image folders,
how many were skipped (already done), and any failures. Then run a quick QA sweep:

- every file carries `source_url:` frontmatter;
- residual-chrome grep is empty (`subscribe for free|user's avatar|ready for more|leave a comment`);
- no suspiciously tiny files (`< ~400 bytes` ⇒ a bad/preview scrape).

For wiki use, remind the user the files are drop-in for `raw/` once each gets a catalog ID
(`raw/NNNN_<slug>/`), and that ingestion is a **separate** later step.

---

## Resumability and rate limits (the operational core)

- **Resume ledger.** Completed post slugs are recorded in `<out>/_done.json`. Re-running the **same
  command** skips them and fetches only what's missing — so an interrupted or rate-limited run is
  resumed by just running it again, and a run weeks later **auto-picks up only NEW posts** the
  author has published since. `--force` ignores the ledger.
- **Rate limiting is real.** Substack returns **HTTP 429** under a fast loop. The engine backs off
  exponentially on 429 (5 s → 90 s), but the durable lesson is: **build resume + backoff in from the
  start** and keep `--delay` ≥ ~1 s. A 0.3 s delay reliably trips the limiter partway through a
  large archive; the resume ledger is what makes recovery painless.
- **`_manifest.json`** (sorted oldest→newest, so the **last/newest post is the bottom row**) and
  `_done.json` are left in the output dir as the run record — keep them with the corpus if you want
  to know later exactly what was fetched and which post was last.

## What this skill does NOT do

- It does not fetch **paywalled** post bodies in full — those return a public preview. It flags them
  (`audience:` frontmatter + `<PREVIEW?>`) so you can fetch them manually from a logged-in browser.
- It assigns **no catalog IDs** and does not touch `raw/` — packaging into a wiki is a later step.
- The cover/thumbnail image (the one shown on the archive listing) is **skipped by design**; only
  genuine in-content images are kept.

## Relationship to neighbouring skills

- **`url-to-md`** — the single-page counterpart: download one arbitrary URL as clean Markdown + its
  images. Reach for `fetch-substack-archive` when you want a **whole Substack publication** in one
  pass; reach for `url-to-md` for one page on any site.
- **`firecrawl-scrape`** — generic page-to-markdown via Firecrawl; works on a single Substack post
  but leaves Substack's comments/subscribe chrome that this skill's API route avoids entirely.
- The LLM-wiki **Source acquisition from URL** workflow — the wiki-side step that packages a fetched
  article into `raw/NNNN_<slug>/` and logs it. This skill produces exactly the self-contained
  Markdown that step expects, in bulk.
