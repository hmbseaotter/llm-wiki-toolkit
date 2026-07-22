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
# --- causal direction vocabulary -------------------------------------------------------------
#
# Hard Rule 8 originally named eight tokens. A 2026-07-21 census of all 4,693 causal bullets found
# 314 distinct tokens in use, and the eight canonical ones covered only ~50% of them: `worsen` (200)
# alone outranks five of the eight. The organic vocabulary is not sloppiness — `deplete` says more
# than `decrease` in a nutrition context — so the schema was widened to match practice rather than
# 2,100 bullets being flattened to eight words.
#
# DIRECTIONS is FROZEN, not open: it was generated once from (observed - rejected) and pasted here,
# so a NEW coinage flags for review instead of being silently absorbed.
DIRECTIONS = {
    "accelerate", "accumulate", "achieve", "activate", "add", "address", "allow", "amplify",
    "attenuate", "automate", "begin", "block", "blunt", "break", "build", "calibrate", "calm",
    "cascade", "cause", "cease", "clear", "close", "co-provide", "collapse", "compete",
    "complete", "compound", "compress", "consume", "contribute", "counterbalance", "crash",
    "create", "cross", "damage", "dampen", "decline", "decrease", "deepen", "degrade", "delay",
    "deliver", "deplete", "deprive", "desensitize", "destabilize", "destroy", "desynchronize",
    "develop", "dim", "disengage", "disinhibit", "displace", "disrupt", "dissolve", "distort",
    "divert", "drive", "drop", "dysregulate", "elevate", "eliminate", "enable", "encourage",
    "enhance", "entrench", "erode", "escalate", "establish", "exacerbate", "exceed", "execute",
    "exhaust", "expose", "extend", "facilitate", "fail", "fatigue", "feed", "fill", "flatten",
    "flush", "force", "form", "fragment", "fuel", "fund", "garble", "gate", "generate", "harden",
    "hide", "impair", "impede", "impose", "improve", "increase", "induce", "inflame", "inhibit",
    "initiate", "install", "intensify", "interrupt", "jam", "keep", "kill", "leave", "lengthen",
    "lift", "limit", "load", "loosen", "lower", "magnify", "maintain", "manufacture", "mask",
    "meet", "mis-signal", "misalign", "misattribute", "mislead", "miss", "mitigate", "moderate",
    "no-effect",
    "multiply", "narrow", "normalize", "obscure", "open", "optimize", "oscillate", "overwhelm",
    "peak", "perpetuate", "persist", "precipitate", "predispose", "preserve", "prevent", "prime",
    "produce", "progress", "promote", "protect", "provide", "rate-limit", "reach", "reactivate",
    "recover", "redirect", "redistribute", "reduce", "refill", "reinforce", "release", "remain",
    "remove", "repair", "replenish", "require", "reset", "resolve", "restart", "restore",
    "retain", "reverse", "rise", "self-sustain", "sensitize", "sequester", "shift", "shrink",
    "signal", "slow", "spike", "stabilize", "stall", "starve", "stimulate", "strengthen",
    "stretch", "substitute", "supply", "support", "suppress", "surge", "sustain", "switch",
    "time", "train", "transcribe", "trigger", "uncouple", "undermine", "upregulate", "weaken",
    "widen", "worsen",
}

# `no-effect` asserts a NON-effect ("X does not affect Y"). Added 2026-07-21 after the
# vocabulary pass surfaced real cases — a sanctioned non-effect matters because "does NOT
# chronically elevate cortisol" is often the clinically important claim, and rewriting it
# positively loses that emphasis. It IS a direction (it states what happens to the target:
# nothing), so it lives in DIRECTIONS rather than in the review-only set.
# `other` is sanctioned by schema/page-format.md's own template as the honest "direction not
# settled" escape hatch. It is NOT an error, but it is not traversable either, so it is reported
# separately for review rather than counted as malformed.
UNKNOWN_DIRECTION = {"other"}

# Why a token was rejected, so the finding can say something actionable instead of "not in list".
REJECTED = {}
for _t in ("abnormal absent acutely baseline biologically chronic chronically continuous "
           "continuously delayed direct directly dramatic dual episodic erratic/premature falsely "
           "far gradual heavy higher impaired inadequate indirect indirectly initial insufficient "
           "irregular long multiple natural near-zero neurochemical not oxidative paradoxically "
           "partial partially permanent post-pill potentially primary progressive rebound relative "
           "severe short strong structural sustained systematically").split():
    REJECTED[_t] = ("qualifier", "modifies a direction but is not one — the real direction is "
                                 "missing or buried after it")
for _t in ("absence deficiency double elevation fat fluctuation fluid insufficiency marker no "
           "overactivity paradox progression receptor resistance result risk vacuum water").split():
    REJECTED[_t] = ("noun", "names a state or the target itself, not the direction of effect")
for _t in ("associate associated confirm correlate guide identify illustrate indicate indicates "
           "link mimic predict represent").split():
    REJECTED[_t] = ("epistemic", "asserts knowledge or correlation, not causation — a correlation "
                                 "is not a causal edge")
for _t in ("affect alter control converge determine express influence interact modulate occur "
           "program regulate respond shape structure vary").split():
    REJECTED[_t] = ("non-directional", "causal but direction-free: says THAT the target is affected, "
                                       "never WHICH WAY it moves")
for _t in ("does fills the when").split():
    REJECTED[_t] = ("artifact", "not a direction token at all — the slot holds a function word or "
                                "an inflected verb form")
del _t

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


_CAUSAL_H2 = ("## what causes this", "## what this causes")
_DASHES = ("—", "–")   # em, en


def split_causal_bullet(line):
    """`- [[target]] — <direction>: <mechanism>` -> (target, token, ok). ok=False if unparseable.

    ORDER MATTERS, and both orderings were tried before this one stuck:
      * scanning for the colon first breaks on a target carrying its own colon, e.g.
        `**Food preference: high-calorie options** — increase (specifically): …`;
      * taking the first em-dash regardless of nesting breaks on a target carrying its own dash,
        e.g. `[[x]] (pre-existing — from restriction) — increase: …`, which silently yielded the
        junk token "from".
    So: collect separators and colons at bracket-depth 0 only, then take the first separator that
    has a colon after it. Depth tracking is what keeps nested punctuation out of the slot."""
    body = line[2:]
    depth, seps, colons = 0, [], []
    for i, c in enumerate(body):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        elif depth == 0:
            if c == ":":
                colons.append(i)
            elif (c in _DASHES and i > 0 and body[i - 1] == " "
                  and i + 1 < len(body) and body[i + 1] == " "):
                seps.append(i)
    for s in seps:
        colon = next((c for c in colons if c > s), None)
        if colon is None:
            continue
        slot = body[s + 1:colon].strip().replace("*", "").strip()
        if not slot:
            continue
        return body[:s].strip(), slot.split()[0].strip("(),").lower(), True
    return None, None, False


def check_causal_bullet_directions(repo, _pages):
    """Hard Rule 8 on CONCEPT pages — where the overwhelming majority of causal edges actually live.

    check_causal_directions (below) only ever scanned Links tables in wiki/causal-chains/, so Hard
    Rule 8 was enforced on a small minority of edges. That gap is how `direction-inconsistent` — not
    a direction token at all — sat unflagged in ashwagandha.md until a human resolution pass tripped
    over it on 2026-07-21.

    Reports three distinct outcomes, because they need different fixes:
      * rejected token  -> the slot holds a qualifier / noun / epistemic / non-directional word
      * unknown token   -> a coinage not in the frozen vocabulary; review and add or replace
      * unparseable     -> the bullet does not have the mandatory `target — direction: mechanism`
                           shape at all"""
    out = []
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in sorted(fs):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            in_causal = False
            for i, line in enumerate(_read(p).split("\n"), 1):
                if line.startswith("## "):
                    in_causal = line.strip().lower().startswith(_CAUSAL_H2)
                    continue
                if not in_causal or not line.startswith("- "):
                    continue
                _, tok, ok = split_causal_bullet(line)
                if not ok:
                    out.append(_finding(
                        "malformed-causal-bullet",
                        "bullet is not in the mandatory `- [[target]] — <direction>: <mechanism>` "
                        "form, so it is not a traversable causal edge",
                        file=rel, line=i,
                        fix="Rewrite to `- [[target]] — <direction>: <mechanism>`. If it is not a "
                            "causal edge at all (a sub-list header, a cross-reference, an evidence "
                            "note), move it to ## Related or out of the causal section."))
                elif tok in REJECTED:
                    kind, why = REJECTED[tok]
                    out.append(_finding(
                        "non-directional-token",
                        f"direction slot holds '{tok}' ({kind}) — {why}",
                        file=rel, line=i,
                        fix="Replace with a token stating which way the target moves "
                            "(schema/page-format.md, 'Mandatory format for causal bullets'). Use "
                            "`other` only when the direction is genuinely unsettled."))
                elif tok not in DIRECTIONS and tok not in UNKNOWN_DIRECTION:
                    out.append(_finding(
                        "unknown-direction-token",
                        f"'{tok}' is not in the sanctioned direction vocabulary",
                        file=rel, line=i,
                        fix="Use an existing token, or — if this is a genuinely new and useful "
                            "direction — add it to DIRECTIONS in tools/structure_qa.py and sync the "
                            "copies. The vocabulary is frozen so coinages surface here for review."))
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


def check_duplicate_causal_targets(repo, _pages):
    """Two bullets to one target in one causal section that do not say how they differ.

    NAMED FOR WHAT IT LOOKED LIKE, NOT WHAT IT FINDS. First full pass (2026-07-21) cleared 23
    findings: 1 was a real duplicate, 22 were genuinely distinct edges whose distinguishing
    condition was missing or buried after the direction token — luteal vs follicular, acute vs
    chronic, onset vs maintenance, deficiency-end vs excess-end. So this is a CLARITY check, and
    the usual fix is to make the condition visible, not to delete a bullet.

    SCOPE IS DELIBERATELY NARROW, because most repetition in this wiki is CORRECT:
      * Cross-page mirroring is the graph itself. `A — increase: B` belongs on A's `What this
        causes` AND B's `What causes this`; that is what makes traversal work from either end.
        Never flag it.
      * A repeated target under DIFFERENT `###` sub-headings is usually two real edges about two
        different subjects — e.g. estriol-vs-estradiol.md states `VTE risk` once under
        "Estradiol replacement" and once under "Estriol replacement". So the sub-heading is part
        of the key; without it this check would flag correct pages.

    What it CANNOT see, and what actually cost us on 2026-07-21: the same mechanism stated once as
    prose in `## How it works` and again as a bullet, in completely different words. No string
    match reaches that — it is reasoning work, and `schema/lint.md` carries it as a lint-pass rule
    instead. This check covers only the mechanical half; do not mistake a clean run for an absence
    of redundancy."""
    out = []
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in sorted(fs):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            section, sub, seen = None, "", {}
            for i, line in enumerate(_read(p).split("\n"), 1):
                if line.startswith("## "):
                    low = line.strip().lower()
                    section = low if low.startswith(_CAUSAL_H2) else None
                    sub = ""
                    continue
                if line.startswith("### "):
                    sub = line.strip()
                    continue
                if not section or not line.startswith("- "):
                    continue
                m = re.match(r"-\s+(.*?)\s+[—–]\s", line)
                if not m:
                    continue
                target = m.group(1).strip().lower().replace("*", "").strip()
                key = (section, sub, target)
                if key in seen:
                    out.append(_finding(
                        "duplicate-causal-target",
                        f"target {m.group(1).strip()!r} already has a bullet in this section "
                        f"(line {seen[key]}) — two edges to one target that do not say "
                        f"how they differ",
                        file=rel, line=i,
                        fix="USUALLY these are two real edges whose distinguishing condition is "
                            "missing or buried after the direction token — put it in the TARGET "
                            "(`[[x]] (luteal) — decrease:`) or group them under `###` sub-headings. "
                            "Merge only when both bullets genuinely make the same claim. If they "
                            "differ because their SOURCES conflict, that is a contradiction, not a "
                            "duplicate — flag it, do not merge (Hard Rule 7)."))
                else:
                    seen[key] = i
    return out


def check_line_endings(repo, _pages):
    """A tracked markdown file whose working copy disagrees with .gitattributes.

    `.gitattributes` declares `* text=auto eol=lf`, so git normalizes on staging and HISTORY can
    never carry CRLF. This check exists for the working copy, where CRLF is not harmless: a
    whole-file ending flip makes `git diff` and `git status` unreadable, which is how a real change
    hides inside apparent noise.

    WHY A CHECK RATHER THAN A RULE. Every agent in the 2026-07-21 session was told to write LF.
    Behaviour was inconsistent anyway, three of them 'fixed' it three different ways, and two
    produced contradictory diagnoses of the cause (the actual culprit was the Control Panel calling
    write_text() without newline="", which Windows text mode translates). A prose instruction is
    advisory and cannot be verified; this is recomputed every run and cannot be forgotten — the same
    posture as the rest of this module."""
    out = []
    if not os.path.exists(os.path.join(repo, ".gitattributes")):
        return out                                    # no declared convention -> nothing to enforce
    for r, _, fs in os.walk(repo):
        if ".git" in r.replace("\\", "/").split("/"):
            continue
        for fn in sorted(fs):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            if rel.startswith("raw/"):                # immutable and not ours to normalize
                continue
            try:
                with open(p, "rb") as fh:
                    blob = fh.read()
            except OSError:
                continue
            if b"\r\n" in blob:
                out.append(_finding(
                    "crlf-line-endings",
                    "working copy has CRLF endings but .gitattributes declares eol=lf — a "
                    "whole-file ending flip makes real changes unreadable in git diff",
                    file=rel,
                    fix="Rewrite the file with LF (in Python: open(p, 'w', encoding='utf-8', "
                        "newline='')). If a tool produced it, fix the tool — write_text() and "
                        "print() translate \\n to \\r\\n on Windows unless newline='' is passed."))
    return out


def _contradiction_bullets(repo):
    """Yield (rel_path, line_no, bullet_lines) for every bullet under `## Contradictions flagged`.

    Shared by the two contradiction checks below. Kept as ONE parser deliberately: on 2026-07-21
    contradiction_qa.py was found to have drifted 100-116 lines across four copies, and two
    hand-maintained copies of this bullet-walk would rot the same way."""
    for r, _, fs in os.walk(os.path.join(repo, "wiki")):
        for fn in sorted(fs):
            if not fn.endswith(".md"):
                continue
            p = os.path.join(r, fn)
            rel = os.path.relpath(p, repo).replace("\\", "/")
            lines = _read(p).split("\n")
            start = next((i for i, l in enumerate(lines) if l.strip() == "## Contradictions flagged"), None)
            if start is None:
                continue
            end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
            section = lines[start + 1:end]
            bullets, cur = [], None
            for k, l in enumerate(section):
                if l.startswith("- "):
                    if cur is not None:
                        bullets.append(cur)
                    cur = [start + 2 + k, [l]]
                elif cur is not None:
                    cur[1].append(l)
            if cur is not None:
                bullets.append(cur)
            for line_no, body in bullets:
                if "\n".join(body).strip("- ").strip():
                    yield rel, line_no, body


def check_unapplied_resolutions(repo, _pages):
    """A resolved contradiction whose decision never reached the page prose.

    The human resolves a contradiction in the Control Panel with a note that is routinely a DIRECTIVE
    ("disregard the tablespoon figure", "this should be marked as an error", "the depletion framing
    should be primary"). The panel writes only the `Status:` line — it edits no prose and calls no
    model. And the moment Status stops being `Unresolved`, contradiction_qa skips the block, so it
    leaves the gate, the aging report, the nag and the panel queue simultaneously.

    `Resolved` is therefore a TERMINAL state, and an unapplied resolution is chased by nothing. This
    check is the only thing standing between a human decision and silent oblivion. Found on
    2026-07-21: all 15 resolved contradictions lacked any application record, and sugar-withdrawal.md
    still taught the framing the human had explicitly demoted five weeks earlier.

    See `schema/contradictions.md`, 'Applying a resolution'."""
    out = []
    for rel, line_no, body in _contradiction_bullets(repo):
        # Only `Resolved` needs application. `Acknowledged` is a deliberate park (the conflict stands
        # as tentative and the prose is meant to keep both readings), and `Unresolved` is covered by
        # the severity gate.
        if not any(re.match(r"Status:\s*Resolved\b", l.strip()) for l in body):
            continue
        # Require a line that STARTS with the marker — resolution notes themselves often contain the
        # word "applied" in prose ("the directional correction has been applied to the Gotchas
        # section"), which must not be mistaken for the machine-readable record.
        if any(l.strip().startswith("Applied:") for l in body):
            continue
        out.append(_finding(
            "unapplied-resolution",
            "contradiction is marked Resolved but carries no `Applied:` record — the human's "
            "resolution may never have reached the page prose, and nothing else will ever chase it",
            file=rel, line=line_no,
            fix="Read the resolution note as an instruction addressed to the page text, edit the "
                "body so it obeys (raw/ is never touched), then add the `Applied:` record with one "
                "`.` entry per edit anchored to its section heading and carrying the verbatim "
                "removed/added text. If genuinely nothing needed changing, record "
                "`Applied: none required - <why>` so 'nothing was needed' and 'nobody looked' stay "
                "distinguishable (schema/contradictions.md, 'Applying a resolution')."))
    return out


def check_contradiction_blocks(repo, _pages):
    """A flagged contradiction missing its required lines is INVISIBLE to the gate.

    contradiction_qa keys off `Status: Unresolved`; the aging report and the severity gate key off
    `Contradiction severity:`. So a block that states a conflict but omits those lines exists for a
    human reader and for nobody else — it cannot block a commit, cannot age, cannot reach the nag,
    and does not appear in the control panel. Found on 2026-07-21: reference-range-trap.md's ferritin
    bullet had a conflict written out with no assessment, no severity and no status at all.

    Checked per bullet inside a `## Contradictions flagged` section. A bullet with a Status of
    Resolved/Acknowledged is complete by definition and only needs its severity token."""
    out = []
    for rel, line_no, body in _contradiction_bullets(repo):
        # causal-chain pages use the INLINE contradiction form documented in
        # schema/page-format.md ("- **A vs B:** claims. Contradiction severity: … Status: …"),
        # which carries no separate `LLM assessment` line. Requiring one there is a false
        # positive against the schema's own format, not a defect.
        is_chain = "/causal-chains/" in rel
        required = [("severity", r"[Cc]ontradiction severity:"), ("status", r"Status:")]
        if not is_chain:
            required.insert(0, ("assessment", r"LLM assessment"))
        txt = "\n".join(body)
        missing = [name for name, pat in required if not re.search(pat, txt)]
        if missing:
            out.append(_finding(
                "incomplete-contradiction",
                "flagged contradiction is missing: " + ", ".join(missing)
                + " — it is invisible to the severity gate and the aging report",
                file=rel, line=line_no,
                fix="Add the missing line(s). Every flagged contradiction needs an "
                    "LLM assessment, a `Contradiction severity:` token and a `Status:` line "
                    "(schema/contradictions.md, 'How to flag a contradiction')."))
    return out


CHECKS = (check_duplicate_slugs, check_index_parity, check_stale_pending_pointers,
          check_broken_assets, check_causal_directions, check_causal_bullet_directions,
          check_contradiction_blocks, check_unapplied_resolutions, check_line_endings,
          check_duplicate_causal_targets)


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
