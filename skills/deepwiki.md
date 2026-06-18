# DeepWiki Digest

Fetches any URL, digests the content into a structured summary, then stays ready for follow-up questions. Works from any directory.

When given a GitHub repo URL, automatically uses DeepWiki for richer structured documentation.

---

## STEP 1 — Resolve the URL

Accept a URL from the user's argument.

- If the URL is `https://github.com/org/repo` → silently convert to `https://deepwiki.com/org/repo` before fetching
- If the URL is already `https://deepwiki.com/org/repo` → use as-is
- Any other URL → use as-is

If no argument is provided, ask the user for the URL before continuing.

---

## STEP 2 — Fetch the Content

Use the `firecrawl` skill to scrape the URL. Request the full page content in markdown.

**For DeepWiki URLs:** also check the page for navigation links to sub-sections (e.g. Architecture, Modules, API Reference, Data Flow). Fetch up to 5 of the most substantive sub-pages. Prioritize pages that describe structure, components, or how pieces connect over pure API reference listings.

If a DeepWiki URL returns a "not indexed" or 404 page, tell the user:
> "DeepWiki hasn't indexed this repo yet. Visit https://deepwiki.com/[org]/[repo] in a browser to trigger indexing, then try again."

---

## STEP 3 — Produce the Digest

Write a structured summary. Use whichever headings are relevant to the content — skip any that don't apply.

```
## What it is
One to three sentences. What is this? What problem does it solve or what does it cover?

## Structure / Organization
How the content or codebase is laid out. Key sections, directories, or categories.

## How the pieces connect
For technical content: architecture and data flow. For documentation: how topics relate.

## Key concepts & terms
Domain-specific vocabulary, patterns, or abstractions a newcomer would need to know.

## Where to start
The best entry point: main page, primary section, key file, or first thing to read.
```

---

## STEP 4 — Invite Follow-up

After presenting the digest, ask:

> "What would you like to explore next? You can ask about a specific section, a term you didn't follow, how something works, or anything else from this content."

Remain in context as a guide for the fetched content for the rest of the session — treat it as your reference material and answer questions against it.
