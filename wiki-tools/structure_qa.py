#!/usr/bin/env python3
"""structure_qa — portable, stdlib-only core for an llm-wiki's STRUCTURAL QA.

Sibling of contradiction_qa.py, for the other half of lint. Contradictions are conflicts between
*claims* and carry a `Status:` marker on the page; structural defects are conflicts between the
repo and its own schema — a duplicate filename, a page missing from the index, a broken image
link. They have no marker, which is exactly why they were invisible:

  WHY THIS EXISTS. On 2026-07-21 the `anxiety-loop` duplicate slug (the same slug used by both
  wiki/concepts/ and wiki/causal-chains/, making every [[anxiety-loop]] link ambiguous) was found
  to have been open since the 2026-07-07 lint — reported twice, in log.md, and seen by nobody.
  Every automated channel that wiki had keys off the `Status: Unresolved` contradiction marker:
  the alert email, the scheduled nag, the pre-commit gate. A structural defect has no such marker,
  so it reached zero of them. The LLM lint pass was doing the work (that same pass also caught 29
  pages missing from index.md and 8 schema violations) and writing it to a file nobody reads.

DESIGN — recompute, never remember. Every check below is a deterministic rescan of the repo, so:
  * no LLM has to remember to record anything (the log.md prose is a record, not a channel), and
  * a finding CLEARS ITSELF the moment the defect is fixed — no resolve-marker to maintain, no
    stale-state file to reconcile. This is the same posture that makes contradiction_qa reliable.
The trade-off is honest and worth stating: this covers the DETERMINISTIC findings. Reasoning-derived
lint findings (a fabricated citation, an inverted causal direction) still live only in log.md.

NON-BLOCKING BY DESIGN. Nothing here gates a commit. The pre-commit hook blocks only on HARD
contradictions — two claims that cannot both be true, where committing would record a known
falsehood as settled. A duplicate slug or a missing index line is a defect to fix at leisure, not a
reason to make the repo uncommittable. Surfacing is the fix for invisibility; blocking is not.

Because it is pure stdlib and free of any orchestrator coupling, the same file drops unchanged into
the compounding-llm-wiki template and any other wiki. A wiki WITHOUT a pipeline needs it most: with
no ingest orchestrator and no nag job there is no email channel at all, so the Tier-1 CLI below —
run by the agent or a human at lint time — is the only thing standing between a structural defect
and permanent invisibility.

Tier-1 CLI:
  python tools/structure_qa.py [--root .]
    -> prints every open structural finding, grouped by kind. No email, no git, no scheduler.
"""
import argparse, os, re, sys

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The sanctioned causal direction vocabulary (CLAUDE.md Hard Rule 8 / schema/causal.md).
DIRECTIONS = {"increase", "decrease", "activate", "inhibit", "trigger", "suppress", "enable", "block"}

# The fixed wording of a pending-pointer, per CLAUDE.md ("the pointer's wording is fixed so it stays
# greppable"). A pointer is STALE once the slug it apologises for actually exists.
_PENDING_RX = re.compile(r"\[\[([^]|#]+)\]\]\s*\*\(page pending[^)]*\)\*")
_LINK_RX = re.compile(r"\[\[([^]|#]+)")
_INDEX_ENTRY_RX = re.compile(r"^- \[\[([^]|#]+)\]\]", re.M)
_IMG_RX = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _wiki_pages(repo):
    """{slug: [relative paths]} for every page under wiki/. A slug with >1 path is the duplicate."""
    out = {}
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in fs:
            if fn.endswith(".md"):
                rel = os.path.relpath(os.path.join(r, fn), repo).replace("\\", "/")
                out.setdefault(fn[:-3], []).append(rel)
    return out


def _finding(kind, detail, file="", line=0, fix=""):
    return {"kind": kind, "detail": detail, "file": file, "line": line, "fix": fix}


def check_duplicate_slugs(repo, pages):
    """Two pages sharing a basename make every [[slug]] to them ambiguous — Obsidian silently picks
    one, so a reader can land on the wrong page with no error anywhere (Hard Rule 6)."""
    out = []
    for slug, paths in sorted(pages.items()):
        if len(paths) > 1:
            out.append(_finding(
                "duplicate-slug",
                f"[[{slug}]] resolves to {len(paths)} files: " + ", ".join(sorted(paths)),
                file=sorted(paths)[0],
                fix="Rename one (usually the causal-chain, to <concept-slug>-cascade) or merge them. "
                    "Merge-vs-rename is a human decision (Hard Rule 7)."))
    return out


def check_index_parity(repo, pages):
    """index.md is the query router: a page missing from it is invisible to routing, and an entry
    with no page is a dead link at the top of every query."""
    out = []
    idx = _read(os.path.join(repo, "index.md"))
    if not idx:
        return out
    listed = set(_INDEX_ENTRY_RX.findall(idx))
    known = set(pages)
    for slug in sorted(known - listed):
        out.append(_finding("page-not-in-index", f"{pages[slug][0]} exists but is not listed in index.md",
                            file=pages[slug][0],
                            fix="Add a one-line entry under its type section in index.md."))
    for slug in sorted(listed - known):
        out.append(_finding("index-entry-orphaned", f"index.md lists [[{slug}]] but no such page exists",
                            file="index.md",
                            fix="Create the page, or remove the index entry if the slug was renamed."))
    return out


def check_stale_pending_pointers(repo, pages):
    """A pending-pointer apologises for a link whose page does not exist yet. Once the page exists
    the apology is wrong, and CLAUDE.md says lint strips it automatically."""
    out = []
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in fs:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            for i, line in enumerate(_read(p).splitlines(), 1):
                for slug in _PENDING_RX.findall(line):
                    if slug.strip() in pages:
                        out.append(_finding("stale-pending-pointer",
                                            f"pointer for [[{slug.strip()}]] is stale — that page now exists",
                                            file=rel, line=i,
                                            fix="Delete the *(page pending — closest coverage: …)* note."))
    return out


def check_broken_assets(repo, _pages):
    """An embedded image whose file is absent renders as a broken image in Obsidian and on GitHub."""
    out = []
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in fs:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            for i, line in enumerate(_read(p).splitlines(), 1):
                for target in _IMG_RX.findall(line):
                    t = target.split(" ")[0].strip()
                    if t.startswith(("http://", "https://", "data:")):
                        continue
                    if not os.path.exists(os.path.normpath(os.path.join(r, t))):
                        out.append(_finding("broken-asset", f"image link does not resolve: {t}",
                                            file=rel, line=i,
                                            fix="Fix the relative path (wiki pages sit two levels below "
                                                "the root, so raw assets need ../../raw/…)."))
    return out


def check_causal_directions(repo, _pages):
    """Hard Rule 8: every causal edge states its direction. A Links row whose Direction cell is not
    in the sanctioned vocabulary breaks traversal and the symptom→cause-tree query."""
    out = []
    chains = os.path.join(repo, "wiki", "causal-chains")
    for r, _, fs in os.walk(chains):
        for fn in fs:
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            in_table = False
            for i, line in enumerate(_read(p).splitlines(), 1):
                s = line.strip()
                if not s.startswith("|"):
                    in_table = False
                    continue
                cells = [c.strip() for c in s.split("|")]
                if len(cells) < 6:
                    continue
                head = cells[1].strip().lower()
                if head in ("from", "") and not in_table:      # header row of a Links table
                    in_table = head == "from"
                    continue
                if set(cells[1]) <= {"-", ":"}:                 # the |---|---| separator
                    continue
                if not in_table:
                    continue
                token = cells[2].strip().lower().replace("*", "").replace("↺", "").strip()
                if token and token.split()[0] not in DIRECTIONS:
                    out.append(_finding("missing-direction",
                                        f"Links row direction '{cells[2].strip()}' is not in the "
                                        "sanctioned vocabulary", file=rel, line=i,
                                        fix="Use one of: " + " / ".join(sorted(DIRECTIONS)) + "."))
    return out


CHECKS = (check_duplicate_slugs, check_index_parity, check_stale_pending_pointers,
          check_broken_assets, check_causal_directions)


def scan_structure(repo=None):
    """Every open structural finding, recomputed from the repo. Order is stable (checks in order,
    each internally sorted) so the same repo state always produces the same report."""
    repo = repo or _REPO
    pages = _wiki_pages(repo)
    out = []
    for chk in CHECKS:
        try:
            out.extend(chk(repo, pages))
        except Exception as e:                    # one broken check must not suppress the others
            out.append(_finding("check-error", f"{chk.__name__} failed: {e}"))
    return out


HELP_FIX = """HOW TO CLEAR A STRUCTURAL FINDING
--------------------------------
These are defects between the repo and its own schema — NOT contradictions, and nothing here blocks
a commit. Each entry names the file, the line, and the fix. There is no marker to edit and nothing
to mark resolved: fix the file and the finding disappears from the next run, because every check is
recomputed from the repo rather than remembered.

Check it yourself any time:   python tools/structure_qa.py"""


def finding_key(f):
    """Stable identity for a finding across runs — used to age it and to detect NEW ones."""
    return f"{f['kind']}|{f['file']}:{f['line']}"


def structure_report(findings, ages=None, escalate_days=30):
    """PURE builder for the structural block. Returns {count, overdue_count, subject, block,
    findings} — `block` is the text that goes at the TOP of an outgoing email (above contradictions:
    a structural defect is a different, and more foundational, class of problem than two sources
    disagreeing).

    `ages` maps finding_key -> days open. Anything past `escalate_days` is listed AGAIN in an OVERDUE
    section at the very top and named in the subject line. This exists because non-blocking findings
    are exactly the kind that get read, nodded at, and left: the anxiety-loop duplicate slug sat open
    for 14 days precisely because nothing ever got louder about it. Age is advisory — it is cached in
    tools/state/, so if that file is lost a finding simply reads as new rather than being lost."""
    if not findings:
        return {"count": 0, "overdue_count": 0, "subject": None, "block": "", "findings": []}
    ages = ages or {}
    by_kind = {}
    for f in findings:
        by_kind.setdefault(f["kind"], []).append(f)
    overdue = sorted([f for f in findings if (ages.get(finding_key(f)) or 0) >= escalate_days],
                     key=lambda f: -(ages.get(finding_key(f)) or 0))
    lines = [f"STRUCTURAL FINDINGS — {len(findings)} open (schema/repo defects, non-blocking)",
             "=" * 64]
    if overdue:
        lines.append(f"\n!! {len(overdue)} OVERDUE — open more than {escalate_days} days. "
                     "These are not going to fix themselves; schedule a pass or decide to accept them.")
        for f in overdue:
            loc = f["file"] + (f":{f['line']}" if f["line"] else "")
            lines.append(f"  - [{ages.get(finding_key(f))}d] {loc} — {f['detail']}")
    for kind in sorted(by_kind):
        items = by_kind[kind]
        lines.append(f"\n{kind} ({len(items)}):")
        for f in items:
            loc = f["file"] + (f":{f['line']}" if f["line"] else "")
            lines.append(f"  - {loc} — {f['detail']}" if loc else f"  - {f['detail']}")
        if items[0].get("fix"):
            lines.append(f"    FIX: {items[0]['fix']}")
    lines += ["", HELP_FIX, "=" * 64, ""]
    kinds = ", ".join(f"{k}×{len(v)}" for k, v in sorted(by_kind.items()))
    subj = f"[corpus-watch] {len(findings)} structural finding(s) — {kinds}"
    if overdue:
        subj += f" — {len(overdue)} OVERDUE"
    return {"count": len(findings), "overdue_count": len(overdue),
            "subject": subj,
            "block": "\n".join(lines),
            "findings": findings}


def main():
    ap = argparse.ArgumentParser(description="Report open structural (schema/repo) defects. Tier 1.")
    ap.add_argument("--root", default=".", help="wiki root (the dir containing wiki/); default cwd")
    a = ap.parse_args()
    repo = os.path.abspath(a.root)
    findings = scan_structure(repo)
    rep = structure_report(findings)
    if not findings:
        print(f"structure-qa | {repo} | 0 structural findings — clean.")
        return
    print(f"structure-qa | {repo} | {rep['count']} open\n")
    print(rep["block"])


if __name__ == "__main__":
    main()
