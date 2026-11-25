"""Stage 2 — Crawl first 3 catalogue pages via 'next' links and collect 60 unique book URLs."""

import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache"

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/rozak-27/task-api)"
TIMEOUT_SECONDS = 10
POLITE_DELAY_SECONDS = 0.55
MAX_CATALOGUE_PAGES = 3

_last_network_request_at: float | None = None


def polite_wait() -> None:
    global _last_network_request_at
    if _last_network_request_at is not None:
        elapsed = time.monotonic() - _last_network_request_at
        if elapsed < POLITE_DELAY_SECONDS:
            time.sleep(POLITE_DELAY_SECONDS - elapsed)


def fetch_html(url: str, cache_path: Path) -> tuple[str, bool]:
    global _last_network_request_at
    if cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
        return html, True

    polite_wait()
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    _last_network_request_at = time.monotonic()

    if response.status_code != 200:
        raise RuntimeError(f"Failed fetch for {url}: HTTP {response.status_code}")

    html = response.content.decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    return html, False


def discover_catalogue_books(start_url: str = START_URL, max_pages: int = MAX_CATALOGUE_PAGES):
    current_url: str | None = start_url
    pages_visited = 0
    discovered_total = 0
    unique_books: dict[str, str] = {}  # canonical product_url -> source_page

    while current_url and pages_visited < max_pages:
        page_num = pages_visited + 1
        cache_file = CACHE_DIR / f"catalogue-page-{page_num}.html"
        html, _ = fetch_html(current_url, cache_file)
        pages_visited += 1

        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("article.product_pod h3 a[href]"):
            abs_book_url = urljoin(current_url, link["href"])
            discovered_total += 1
            if abs_book_url not in unique_books:
                unique_books[abs_book_url] = current_url

        next_anchor = soup.select_one("li.next a[href]")
        current_url = urljoin(current_url, next_anchor["href"]) if next_anchor else None

    return pages_visited, discovered_total, unique_books


def main() -> None:
    pages_visited, discovered_total, unique_books = discover_catalogue_books()
    print(
        f"catalogue_pages={pages_visited}, "
        f"discovered={discovered_total}, "
        f"unique_urls={len(unique_books)}"
    )


if __name__ == "__main__":
    main()
