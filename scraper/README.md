# The Polite Scraper (Assignment A9)

A polite, deterministic web-scraping pipeline built with **Python**, **Requests**, **Beautiful Soup**, and **Pydantic**.

## Target Classification

- **Target Site**: [Books to Scrape](https://books.toscrape.com) (listed at [toscrape.com](https://toscrape.com)).
- **Why This Target Is Permitted**: On `https://toscrape.com`, the site explicitly states: *"Books — A fictional bookstore that desperately wants to be scraped. It's a safe place for beginners learning web scraping and for developers validating their scraping technologies as well."*
- **`robots.txt` Check (`https://books.toscrape.com/robots.txt`)**: Returned HTTP `404` — **no robots file found**. (A missing `robots.txt` is not permission on its own; permission comes strictly from the explicit sandbox statement on `toscrape.com`.)
- **Collection Scope**: Strictly the **first 3 catalogue pages** (`catalogue/page-1.html` through `catalogue/page-3.html`), visiting **60 book detail pages** in total.
- **Data Collected**: Public fictional book catalogue metadata only — `title`, `product_url`, `price_text`, `price_gbp`, `availability_text`, `rating_text`, `description` (when present), plus provenance (`source_page`, `fetched_at`). No user accounts or personal data exist on the site.
- **Why This Is Appropriate**: Collecting 63 static HTML pages once (with local caching, a 500 ms+ delay between requests, and an identifying `User-Agent`) from a dedicated public practice sandbox imposes negligible load and matches the site's intended educational purpose.

> **Commitment**: I will not reuse this code on another site without checking its rules and terms first.
