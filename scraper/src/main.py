"""Stage 1 — Polite fetch with User-Agent, timeout, status check, and local HTML cache."""

from pathlib import Path
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
CACHE_DIR = BASE_DIR / "cache"

START_URL = "https://books.toscrape.com/catalogue/page-1.html"
USER_AGENT = "FlyRankInternship-A9/1.0 (+https://github.com/rozak-27/task-api)"
TIMEOUT_SECONDS = 10


def fetch_html(url: str, cache_path: Path) -> tuple[str, bool]:
    """Return (html_text, from_cache). Checks HTTP 200 and caches UTF-8 HTML."""
    if cache_path.exists():
        html = cache_path.read_text(encoding="utf-8")
        print(f"CACHE HIT {url} ({len(html.encode('utf-8'))} bytes)")
        return html, True

    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise RuntimeError(f"Failed fetch for {url}: HTTP {response.status_code}")

    # Decode explicitly as UTF-8 so '£' never turns into 'Â£'
    html = response.content.decode("utf-8")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(html, encoding="utf-8")
    print(f"FETCH {url} ({len(response.content)} bytes)")
    return html, False


def main() -> None:
    cache_file = CACHE_DIR / "catalogue-page-1.html"
    fetch_html(START_URL, cache_file)


if __name__ == "__main__":
    main()
