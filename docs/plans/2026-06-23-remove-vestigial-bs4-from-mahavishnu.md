---
status: draft
role: implementation
date: 2026-07-16
last_reviewed: 2026-07-16
superseded_by: null
topic: vestigial-bs4-removal
---

# Remove Vestigial beautifulsoup4 from Mahavishnu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Goal:** Remove the unused `beautifulsoup4` dependency from Mahavishnu's `pyproject.toml` and fix three stale doc references that claim BeautifulSoup is used for webpage ingestion.
> **Architecture:** Pure cleanup. No code changes — bs4 has zero imports across `mahavishnu/`, `tests/`, and `examples/`. The actual webpage ingestion in `ContentIngester` delegates to a `web_reader` MCP server on port 8699; nothing in this repo parses HTML locally. A future `bodai-crow-server` (per `docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md`) will use `trafilatura` + `selectolax` for the actual parsing work — in *that* component, not this one.
> **Tech Stack:** Python 3.13, uv, pyproject.toml (PEP 621), pytest.

## Global Constraints

- **No new code dependencies.** This plan removes one; it does not add any.
- **No `selectolax`/`trafilatura` import in this repo.** Those belong to bodai-crow-server per the existing spec.
- **One commit, scoped to Mahavishnu only.** Other bodai components (fastblocks, splashstand, akosha, dhara, crackerjack, session-buddy, oneiric, fastblocks-ui, fastblocks-htmy) already have zero bs4 references — nothing to do there.
- **Verify before commit:** `uv lock --check`, `uv pip check`, `pytest tests/unit -x`, `mahavishnu --help` all succeed after the change.

______________________________________________________________________

## Findings That Justify This Plan

Verified on 2026-06-23 against `/Users/les/Projects/mahavishnu`:

| Probe | Result |
|---|---|
| `from bs4 / import bs4 / BeautifulSoup(...)` across `mahavishnu/`, `tests/`, `examples/` | **0 matches** |
| `beautifulsoup4` in `pyproject.toml` runtime deps (line 68) | `"beautifulsoup4>=4.14.3"` |
| `beautifulsoup4` in `pyproject.toml` dev/test group (line 345) | `"beautifulsoup4"` |
| `CLAUDE.md:401` | "Webpages (via BeautifulSoup HTTP fetching)" — **stale** |
| `docs/DATA_INGESTION.md:11` | "Webpages (via BeautifulSoup HTTP fetching)" — **stale** |
| `docs/CONTENT_INGESTION_GUIDE.md:25` | `uv pip install pypdf ebooklib beautifulsoup4` — **stale** |
| Actual webpage ingestion in `content_ingester.py` | Delegates to `_web_reader_url` MCP server (default `http://localhost:8699/mcp`) — no local HTML parsing |
| `selectolax` anywhere in this repo | Not present (correct — it belongs to bodai-crow-server per spec) |

bs4 is a **vestigial dependency** — declared but never imported.

______________________________________________________________________

## Task 1: Verify bs4 Is Not Transitively Required

**Files:**

- Read: `pyproject.toml` (entire file)

**Why first:** If any *other* listed dep pulls bs4 in transitively, removing it from this repo's `pyproject.toml` won't actually shrink the install (uv will still install it for the dep). Better to know now than at the commit gate.

- [ ] **Step 1: Inspect direct deps for bs4-importing packages**

Run this grep against `pyproject.toml`:

```bash
grep -nE 'httpx|llama-index|pypdf|ebooklib|pydantic-ai|runpod-flash|tavily|markdownify|trafilatura|selectolax|feedparser' /Users/les/Projects/mahavishnu/pyproject.toml
```

Expected: a list of ~15 packages. Note any whose PyPI metadata *might* pull bs4 transitively. The known candidates to check on PyPI are: `llama-index-core` (does *not* depend on bs4), `pypdf` (no), `ebooklib` (no), `pydantic-ai-slim` (no), `markdownify` (no).

- [ ] **Step 2: Resolve the lockfile to see actual transitive deps**

```bash
cd /Users/les/Projects/mahavishnu
uv lock --check
uv pip install --dry-run --quiet | sort -u > /tmp/mahavishnu_install_plan.txt
grep -i "beautifulsoup\|bs4" /tmp/mahavishnu_install_plan.txt
```

Expected output:

```
(no matches)
```

If `bs4` or `beautifulsoup4` appears, **stop and report** — the plan needs a follow-up task to find the offending dep. Don't proceed.

- [ ] **Step 3: Confirm no string-form `monkeypatch.setattr` test points at bs4**

```bash
grep -rn "bs4\|BeautifulSoup" /Users/les/Projects/mahavishnu/tests /Users/les/Projects/mahavishnu/conftest.py 2>/dev/null
```

Expected: zero matches. (Already verified 2026-06-23; re-confirm in case of new tests since then.)

______________________________________________________________________

## Task 2: Remove bs4 from `pyproject.toml` and Fix Stale Docs (single commit)

**Files:**

- Modify: `pyproject.toml:68` (runtime deps)

- Modify: `pyproject.toml:345` (dev/test group)

- Modify: `CLAUDE.md:401`

- Modify: `docs/DATA_INGESTION.md:11`

- Modify: `docs/CONTENT_INGESTION_GUIDE.md:25`

- [ ] **Step 1: Edit `pyproject.toml` runtime dependencies — remove bs4**

In `/Users/les/Projects/mahavishnu/pyproject.toml`, delete line 68. The file content around the change goes from:

```toml
    # Content ingestion
    "pypdf>=6.12.2",
    "beautifulsoup4>=4.14.3",
    "httpx[http2]>=0.28.1",
    "ebooklib>=0.20",
```

to:

```toml
    # Content ingestion
    "pypdf>=6.12.2",
    "httpx[http2]>=0.28.1",
    "ebooklib>=0.20",
```

Use the Edit tool with `old_string` = the entire 5-line block above (with the trailing `httpx` line included to keep the match unique), `new_string` = the 4-line block without bs4.

- [ ] **Step 2: Edit `pyproject.toml` dev/test group — remove bs4**

In `/Users/les/Projects/mahavishnu/pyproject.toml`, delete line 345 (`"beautifulsoup4",`). It sits between `"croniter",` (line 344) and `"gitpython",` (line 346). After removal, lines 344–346 read:

```toml
    "croniter",
    "gitpython",
```

- [ ] **Step 3: Fix `CLAUDE.md:401` — replace stale description**

In `/Users/les/Projects/mahavishnu/CLAUDE.md`, change line 401 from:

```markdown
- Webpages (via BeautifulSoup HTTP fetching)
```

to:

```markdown
- Webpages (delegated to `web_reader` MCP server on port 8699)
```

Context (lines 399–403) confirms this is the "Supported Content Types" list under the `ContentIngester` section; the new wording matches the actual implementation in `content_ingester.py:175`.

- [ ] **Step 4: Fix `docs/DATA_INGESTION.md:11` — same wording fix**

In `/Users/les/Projects/mahavishnu/docs/DATA_INGESTION.md`, change line 11 from `- Webpages (via BeautifulSoup HTTP fetching)` to `- Webpages (delegated to \`web_reader\` MCP server on port 8699)\`.

- [ ] **Step 5: Fix `docs/CONTENT_INGESTION_GUIDE.md:25` — drop bs4 from install command**

In `/Users/les/Projects/mahavishnu/docs/CONTENT_INGESTION_GUIDE.md`, change line 25 from:

```markdown
uv pip install pypdf ebooklib beautifulsoup4
```

to:

```markdown
uv pip install pypdf ebooklib
```

- [ ] **Step 6: Re-run verification suite**

```bash
cd /Users/les/Projects/mahavishnu
uv lock --check                                            # Should still pass (no transitive bs4 was being pinned)
uv lock                                                    # regenerate
grep -i "beautifulsoup\|bs4" pyproject.toml uv.lock        # Expect: zero matches
uv pip install --dry-run --quiet | grep -i "bs4"            # Expect: zero matches
pytest tests/unit -x -q --no-header                         # Should pass; if anything imports bs4 we missed, it fails fast
```

If `uv lock` complains about bs4 being a constraint mismatch, **stop** — Task 1 missed a transitive dep. Investigate before continuing.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/mahavishnu
git add pyproject.toml uv.lock CLAUDE.md docs/DATA_INGESTION.md docs/CONTENT_INGESTION_GUIDE.md
git commit -m "chore(deps): remove unused beautifulsoup4 dependency

bs4 was declared but never imported anywhere in mahavishnu/, tests/, or
examples/. Webpage ingestion in ContentIngester delegates to the
web_reader MCP server on port 8699 and does no local HTML parsing.

This commit:
- Drops 'beautifulsoup4>=4.14.3' from runtime deps (pyproject.toml:68)
- Drops 'beautifulsoup4' from the dev/test group (pyproject.toml:345)
- Fixes three stale doc references that claimed BeautifulSoup was the
  webpage fetcher (CLAUDE.md:401, docs/DATA_INGESTION.md:11,
  docs/CONTENT_INGESTION_GUIDE.md:25)

When the bodai-crow-server MCP (port 8675) ships per
docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md, it will
adopt trafilatura + selectolax for the actual web_fetch work. That is a
separate component and a separate dep declaration.

Verified: uv lock passes, no transitive bs4 in resolved tree, pytest
tests/unit -x passes.

Co-Authored-By: Claude <noreply@anthropic.com>"
```

______________________________________________________________________

## Task 3: Ecosystem-wide Audit (informational, no commit)

**Files:** None modified. Just a verification record.

This task confirms bs4 is dead code across the *entire* Bodai ecosystem, not just Mahavishnu. The output should land as a comment on the PR, not as a commit.

- [ ] **Step 1: Run the cross-repo audit**

```bash
for d in /Users/les/Projects/mahavishnu /Users/les/Projects/fastblocks /Users/les/Projects/fastblocks-ui /Users/les/Projects/fastblocks-htmy /Users/les/Projects/splashstand /Users/les/Projects/css-mcp /Users/les/Projects/akosha /Users/les/Projects/dhara /Users/les/Projects/crackerjack /Users/les/Projects/session-buddy /Users/les/Projects/oneiric; do
  [ -d "$d" ] || continue
  echo "=== $(basename "$d") ==="
  grep -lE "from bs4|import bs4|BeautifulSoup\(" "$d" --include="*.py" -r 2>/dev/null | grep -v "\.claude/worktrees" | head -3 || echo "  no bs4 imports"
  grep -E "beautifulsoup4" "$d/pyproject.toml" 2>/dev/null | head -1 || echo "  no bs4 in pyproject"
done
```

Expected result (verified 2026-06-23):

```
=== mahavishnu ===        (bs4 in pyproject; 0 imports — being removed by Task 2)
=== fastblocks ===        no bs4 imports, no bs4 in pyproject
=== fastblocks-ui ===     no bs4 imports, no bs4 in pyproject
=== fastblocks-htmy ===   no bs4 imports, no bs4 in pyproject
=== splashstand ===       no bs4 imports, no bs4 in pyproject (uses nh3 for sanitization)
=== css-mcp ===           no bs4 imports, no bs4 in pyproject (uses tinycss2 + httpx + re)
=== akosha ===            no bs4 imports, no bs4 in pyproject
=== dhara ===             no bs4 imports, no bs4 in pyproject
=== crackerjack ===       no bs4 imports, no bs4 in pyproject
=== session-buddy ===     no bs4 imports, no bs4 in pyproject
=== oneiric ===           no bs4 imports, no bs4 in pyproject
```

**Notes on two adjacent repos:**

- **splashstand** — uses `nh3` (Rust-backed ammonia) for HTML *sanitization* in `splashstand/security/html_sanitizer.py`. nh3 is the right tool for that job and is not a substitute for a parser. Not touched by this plan.

- **css-mcp** — uses `tinycss2~=1.5.1` for CSS parsing in its analyzer and `httpx + re` for HTML extraction in `css_mcp/mdn_fetcher.py` (parses MDN doc pages with regex). If css-mcp ever upgrades from regex to a proper HTML parser for MDN page extraction, **`selectolax` is the better fit than `bs4`** — same reasoning as the bodai-crow-server spec. Not action now; flagged for future consideration.

- [ ] **Step 2: Note the bodai-crow-server precedent**

`/Users/les/Projects/mahavishnu/docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md` (the future web-fetching MCP server on port 8675) already specifies `selectolax~=0.3` + `trafilatura~=2.1` for its CSS fallback path. That component, when implemented, will own the only legitimate HTML-parsing dep in the ecosystem — and it will *not* be bs4.

- [ ] **Step 3: Add the audit result as a PR comment**

After Task 2's commit is pushed and the PR is open, paste the output of Step 1 into a comment so reviewers see this cleanup was ecosystem-scoped, not Mahavishnu-scoped.

______________________________________________________________________

## Out of Scope (Explicitly)

- **Adding `selectolax` to any repo.** The actual parser work belongs to bodai-crow-server; nothing in any bodai component does local HTML parsing today.
- **Removing `nh3` from splashstand.** `nh3` (Rust-backed ammonia) is the right tool for HTML *sanitization*, which is a different problem than parsing or extraction. Splashstand's `html_sanitizer.sanitize()` is correct as-is.
- **Removing `pypdf` or `ebooklib`.** Both have real consumers in `content_ingester.py` (book ingestion).
- **Touching `httpx[http2]`.** That backs the `_web_reader_client`, `_akosha_client`, etc. — actively used.
- **Cross-repo PR.** This is a Mahavishnu-only change. The other nine bodai repos don't have bs4 to remove.

______________________________________________________________________

## Self-Review

**1. Spec coverage:** The user's two asks were (a) "make the removal commit in the plan" → Task 2 step 7. (b) "check bs4 usage in other bodai components" → Task 3 step 1. Both covered.

**2. Placeholder scan:** No "TBD", no "similar to Task N", no "implement later". Every step shows exact commands and exact file paths. The only "expected" outputs are concrete (zero matches, lockfile passes, pytest passes).

**3. Type/symbol consistency:** N/A — no new code, no new types.

**Gaps found during review:** None. The plan is small on purpose: removal of dead code, plus doc corrections, plus an audit record. No new architecture, no new APIs.

______________________________________________________________________

## Why `selectolax` Over `bs4` For Future Use (Reference, Not Action)

When bodai-crow-server ships, the relevant comparison for *that* codebase will be:

| Need | bs4 | selectolax |
|---|---|---|
| Speed (large HTML docs) | ~1× baseline | **~10–30× faster** (Lexbor in C) |
| CSS selector completeness | Soup Sieve: limited `:has()`, partial `nth-*` | Full Lexbor CSS: `:has()`, `nth-child(2n+1)`, etc. |
| HTML5 spec compliance | Depends on backend (`html.parser` lenient, `lxml` strict) | Lexbor: HTML5-spec compliant |
| Tree mutation | Full (insert/replace/remove) | Append/prepend only — read-mostly |
| Mature ecosystem | 20 years, ubiquitous | ~7 years, well-tested, smaller community |

**For our usage** (CSS-selector fallback when trafilatura under-extracts an article body), selectolax wins on every axis that matters: speed (hot path of a server), CSS completeness (we need `:not(:has(...))` and similar), and HTML5 correctness. bs4 would only beat it if we needed in-place tree mutation or XML parsing — neither is on the bodai-crow-server roadmap. The existing spec (`docs/superpowers/specs/2026-06-21-bodai-crow-server-design.md:342`) already chose selectolax for the right reasons.

**For Mahavishnu specifically:** neither library belongs here. This repo is an MCP client for `web_reader`; it doesn't parse HTML. The plan above is just cleanup of a vestigial declaration.
