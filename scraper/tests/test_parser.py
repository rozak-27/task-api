"""Unit tests for parser extraction, normalization, URL resolution, deduplication, and validation."""

import json
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from main import (  # noqa: E402
    compute_retry_wait,
    deduplicate_urls,
    extract_raw_book,
    normalize_and_validate,
    normalize_price_gbp,
    resolve_book_url,
    should_retry_status,
    store_books_with_change_detection,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


def test_price_normalization():
    assert normalize_price_gbp("£51.77") == 51.77
    assert normalize_price_gbp("  £9.50 ") == 9.50
    with pytest.raises(ValueError):
        normalize_price_gbp("£FREE")
    with pytest.raises(ValueError):
        normalize_price_gbp("")


def test_relative_to_absolute_urls():
    assert (
        resolve_book_url(
            "https://books.toscrape.com/catalogue/page-1.html",
            "a-light-in-the-attic_1000/index.html",
        )
        == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )
    assert (
        resolve_book_url(
            "https://books.toscrape.com/catalogue/category/books_1/index.html",
            "../../a-light-in-the-attic_1000/index.html",
        )
        == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    )


def test_missing_description_and_extra_whitespace_fixture():
    html = (FIXTURES_DIR / "book_missing_description.html").read_text(encoding="utf-8")
    raw = extract_raw_book(
        html,
        product_url="https://books.toscrape.com/catalogue/silent-book_1/index.html",
        source_page="https://books.toscrape.com/catalogue/page-1.html",
        fetched_at="2026-11-25T12:00:00Z",
    )
    assert raw["title"] == "Silent Book Without Summary"
    assert raw["availability_text"] == "In stock (5 available)"
    assert raw["description"] is None

    validated, err = normalize_and_validate(raw)
    assert err is None
    assert validated is not None
    assert validated.price_gbp == 19.99
    assert validated.description is None


def test_duplicate_urls_and_idempotent_storage(tmp_path: Path):
    pairs = [
        ("https://books.toscrape.com/catalogue/book-a/index.html", "https://books.toscrape.com/catalogue/page-1.html"),
        ("https://books.toscrape.com/catalogue/book-b/index.html", "https://books.toscrape.com/catalogue/page-1.html"),
        ("https://books.toscrape.com/catalogue/book-a/index.html", "https://books.toscrape.com/catalogue/page-2.html"),
    ]
    deduped = deduplicate_urls(pairs)
    assert len(deduped) == 2

    html = (FIXTURES_DIR / "book_missing_description.html").read_text(encoding="utf-8")
    raw = extract_raw_book(
        html,
        product_url="https://books.toscrape.com/catalogue/book-a/index.html",
        source_page="https://books.toscrape.com/catalogue/page-1.html",
        fetched_at="2026-11-25T12:00:00Z",
    )
    rec, _ = normalize_and_validate(raw)
    assert rec is not None

    out_json = tmp_path / "books.json"
    merged1, changes1 = store_books_with_change_detection([rec], out_json)
    merged2, changes2 = store_books_with_change_detection([rec], out_json)
    assert len(merged1) == 1 and changes1["new"] == 1
    assert len(merged2) == 1 and changes2["unchanged"] == 1
    assert len(json.loads(out_json.read_text(encoding="utf-8"))) == 1


def test_malformed_fixture_rejected_with_reason():
    html = (FIXTURES_DIR / "book_malformed.html").read_text(encoding="utf-8")
    raw = extract_raw_book(
        html,
        product_url="https://books.toscrape.com/catalogue/corrupted_1/index.html",
        source_page="https://books.toscrape.com/catalogue/page-1.html",
        fetched_at="2026-11-25T12:00:00Z",
    )
    validated, err = normalize_and_validate(raw)
    assert validated is None
    assert err is not None
    assert err["product_url"] == "https://books.toscrape.com/catalogue/corrupted_1/index.html"
    assert "price" in err["reason"].lower()


def test_retry_rules_and_retry_after_header():
    assert should_retry_status(404) is False
    assert should_retry_status(403) is False
    assert should_retry_status(429) is True
    assert should_retry_status(503) is True
    assert compute_retry_wait(1, retry_after_header="4") == 4.0
    assert 1.05 <= compute_retry_wait(1, retry_after_header=None) <= 1.25
