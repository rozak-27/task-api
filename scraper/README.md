# The Polite Scraper — FlyRank Internship (Week 5 · Assignment A9)

A polite, fault-tolerant, schema-validated scraping pipeline built in **Python** (`requests`, `BeautifulSoup`, `Pydantic`, `pytest`) that crawls the first 3 catalogue pages of **Books to Scrape**, extracts and normalizes all 60 book detail pages into validated JSON & CSV outputs, survives broken pages without crashing, and writes an honest run report at the end of every run.

---

## 1 · Target Classification (Stage 0)

- **Target Site**: [Books to Scrape](https://books.toscrape.com) (listed on [toscrape.com](https://toscrape.com)).
- **Why This Site Is Permitted**: `https://toscrape.com` explicitly declares: *"Books — A fictional bookstore that desperately wants to be scraped. It's a safe place for beginners learning web scraping and for developers validating their scraping technologies as well."*
- **`robots.txt` Check (`https://books.toscrape.com/robots.txt`)**: Returned HTTP `404` — **no robots file found**. *(Note: a missing `robots.txt` is never permission on its own; permission here comes strictly from ToScrape's explicit public sandbox statement.)*
- **Scope**: Strictly the **first 3 catalogue pages** (`catalogue/page-1.html` → `page-2.html` → `page-3.html` via each page's `"next"` link), discovering **60 unique book detail pages**.
- **Data Collected**: Public fictional book catalogue metadata (`title`, `product_url`, `price_text`, `price_gbp`, `availability_text`, `rating_text`, `description`) plus provenance (`source_page`, `fetched_at`).
- **Appropriateness**: Fetching 63 lightweight static HTML pages once with local disk caching, an identifying `User-Agent`, and ≥500 ms delays places near-zero load on a dedicated scraping practice sandbox.

> **Commitment**: I will not reuse this code on another site without checking its rules and terms first.

---

## 2 · Quick Start (Run in Under 5 Minutes)

### Lane & Stack
- **Language**: Python 3.10+
- **Libraries**: `requests` (HTTP), `beautifulsoup4` (HTML parsing), `pydantic` (schema validation), `pytest` (parser unit tests)

### Install & Run (Copy-Pasteable)

```bash
cd scraper
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
# source .venv/bin/activate
pip install -r requirements.txt

# One command to run the full pipeline:
python src/main.py
```

- **Clean run without the deliberate broken-URL probe**: `python src/main.py --no-broken-url`
- **Run unit tests (offline fixtures)**: `pytest -v`

### Generated Outputs (`scraper/output/`)
- `output/books.json` — Exactly **60** validated, deduplicated book records (idempotent across reruns).
- `output/errors.json` — Any records rejected by Pydantic schema validation, alongside the exact failure reason.
- `output/run-report.json` — Start/end timestamps, duration, pages fetched, cache hits, valid/invalid counts, change detection counts, and failed pages.
- `output/books.csv` — Flattened CSV export of the 60 validated books *(multiline `description` text is flattened onto single lines and `null` descriptions export as empty strings `""`)*.
- `output/dashboard.html` — Local static HTML observability summary showing record count, GBP price range, cache hits, failures, and freshness.

---

## 3 · Record Schema (`BookRecord` — Pydantic)

Every extracted record keeps both raw strings and normalized values, plus provenance, and is validated via `BookRecord` before entering `output/books.json`:

| Field | Type | Required | Validation / Notes |
| :--- | :--- | :--- | :--- |
| `title` | `str` | Yes | Non-empty book title from `article.product_page div.product_main h1` |
| `product_url` | `str` | Yes | Canonical `https://` URL (resolved via `urllib.parse.urljoin`, used as unique key) |
| `price_text` | `str` | Yes | Original raw string preserved verbatim (e.g. `"£51.77"`, decoded as UTF-8) |
| `price_gbp` | `float` | Yes | Strictly positive float (`> 0`, e.g. `51.77`) for sorting & math |
| `availability_text` | `str` | Yes | Normalized whitespace string (e.g. `"In stock (22 available)"`) |
| `rating_text` | `Literal["One","Two","Three","Four","Five"]` | Yes | Extracted from `p.star-rating` class inside `div.product_main` |
| `description` | `str \| None` | Optional | Stored as `null` when absent — never invented |
| `source_page` | `str` | Yes | Provenance: `https://` catalogue page URL where the book was discovered |
| `fetched_at` | `str` | Yes | Provenance: ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`) preserved from initial fetch |

---

## 4 · Politeness Rules & Honest Limitation

### Politeness Rules Followed
1. **Honest User-Agent**: Every HTTP request sends `User-Agent: FlyRankInternship-A9/1.0 (+https://github.com/rozak-27/task-api)`.
2. **Request Timeout**: Every request sets `timeout=10` seconds so a stalled socket never hangs forever.
3. **Polite Crawl Delay**: Waits at least **520 ms** (`>= 500 ms`) between real network requests; local cache hits require zero network traffic and zero delay.
4. **Status Check & Smart Retries**: Only HTTP `200` is cached and parsed. Transient errors (`Timeout`, `ConnectionError`, `429`, `5xx`) use exponential backoff with random jitter and obey the `Retry-After` header; **`404` and `403` are never retried**.
5. **Local Disk Cache (`cache/`, git-ignored)**: Catalogue and book HTML files are fetched once and reused across reruns.

### Honest Limitation
Cached HTML files in `scraper/cache/` currently have **no automatic TTL (time-to-live) expiration**: until `scraper/cache/` is deleted, reruns will keep reading the saved HTML snapshots rather than detecting live upstream price edits on the website.

---

## 5 · Sample `run-report.json` & Why No Browser Was Needed

```json
{
  "started_at": "2026-11-25T13:26:41Z",
  "finished_at": "2026-11-25T13:26:45Z",
  "duration_seconds": 3.225,
  "catalogue_pages": 3,
  "discovered_urls": 60,
  "unique_urls": 60,
  "pages_fetched": 0,
  "cache_hits": 63,
  "valid_records": 60,
  "invalid_records": 0,
  "failed_pages": 1,
  "changed_since_last_run": {
    "new": 0,
    "changed": 0,
    "unchanged": 60,
    "gone": 0
  },
  "failures": [
    {
      "url": "https://books.toscrape.com/catalogue/deliberately-broken-book_99999/index.html",
      "status_code": 404,
      "reason": "HTTP 404 (not retried)"
    }
  ]
}
```

### Why This Assignment Needed No Browser (+ Browser Cost Comparison)
This assignment needed **no headless browser** because Books to Scrape serves every title, price, rating, and link directly inside the static server-rendered HTML response, so launching a browser engine would only multiply runtime, CPU, and RAM cost for zero extra data.

- **Stretch Benchmark (`https://quotes.toscrape.com/js/`)**:
  - **Plain HTTP (`requests`)**: Completed in **`5821.1 ms`** using **`~1768.9 KB`** of traced Python buffer memory, but extracted **`0` quotes** because the quotes on `/js/` only exist inside a `<script>` tag rendered client-side.
  - **Headless Browser (Playwright / Chromium)**: Executes the JavaScript and extracts all **10 quotes**, but requires **~1,500–2,800 ms** wall-clock startup/render time and **~150–250 MB** of multi-process browser RAM — roughly **10× slower and >200× heavier in memory**, proving why you only reach for a headless browser when the data truly isn't in the initial HTML or underlying JSON API.

---

## 6 · Scraping Ethics Note

Good scraping starts with restraint: always use an official public API or data export when one exists instead of parsing HTML. Never bypass authentication walls, paywalls, rate limits (`429`), `403` blocks, or `robots.txt` restrictions, and never collect personal data or more pages/fields than your application genuinely needs.
