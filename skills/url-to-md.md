# URL to Markdown Downloader

Downloads any URL as a clean markdown file plus all of its content images into one self-contained
folder. Image links inside the markdown are rewritten to relative `images/<filename>` paths, so the
folder is fully portable — it can be moved, zipped, or dropped into another project without any
link breaking.

Engine: Firecrawl CLI (`firecrawl`). If it is not installed or not authenticated, tell the user and
stop — do not silently substitute a lossier fetcher.

---

## STEP 1 — Resolve inputs

- **URL:** from the user's argument. If missing, ask.
- **Target folder:** second argument if given; otherwise derive a kebab-case slug from the page
  title and create `<slug>/` in the current working directory.
- Never overwrite an existing folder — if the target exists, ask before proceeding.

---

## STEP 2 — Fetch the markdown

```
firecrawl scrape <URL> --only-main-content -f markdown -o <folder>/article.md
```

`--only-main-content` strips navigation, headers/footers, and sidebars.

---

## STEP 3 — Download the images

1. Extract every image URL from the markdown (`![alt](url)` plus any `<img src>` remnants).
2. Skip obvious non-content assets: tracking pixels, social/share buttons, comment-widget avatars.
   Keep everything that is part of the article itself — when in doubt, keep.
3. Download each into `<folder>/images/`, keeping the original filename (strip query strings;
   de-duplicate name collisions by suffixing `-2`, `-3`, …).
   PowerShell: `Invoke-WebRequest -Uri <url> -OutFile <folder>\images\<name>`.

---

## STEP 4 — Rewrite the links

Replace each remote image URL in `article.md` with its relative `images/<filename>` path. If an
image failed to download, leave its remote URL in place and note it for the report.

---

## STEP 5 — Verify and report

- Every rewritten image link resolves to a local file; list any links left remote (failed
  downloads).
- Content sanity: title present; content reads complete — no paywall stub or truncation (gated
  pages fetched without credentials typically end abruptly at a subscribe prompt); no leftover
  nav/widget junk.
- Report: folder path, markdown size, image count, and any issues found.

> **Note on paywalled pages:** access to subscriber-only content lives in browser session cookies,
> not in the URL — the fetch engine receives the public preview even if the user is logged in
> in their own browser. If the QA check suggests a truncated/gated page, say so explicitly.
