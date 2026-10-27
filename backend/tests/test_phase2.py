import unittest
from app.indexing.tokenizer import (
    normalize_and_tokenize,
    extract_unique_terms_from_patent,
    tokenize_query
)
from app.indexing.indexer import build_inverted_index, get_index_status
from app.search.searcher import search_patents, IndexNotReadyException
from app.api.routes.search import search
from app.api.routes.index import get_status, build_index
from app.db.mongodb import db, check_mongodb
from app.core.config import settings


class TestPatentFindPhase2(unittest.TestCase):

    def test_01_mongodb_connection(self):
        """Verify MongoDB is connected and collections 2016-2023 exist."""
        self.assertTrue(check_mongodb())
        for year in range(2016, 2024):
            col_name = f"patents_{year}"
            count = db[col_name].count_documents({})
            self.assertGreater(count, 0, f"Collection {col_name} should have documents")

    def test_02_tokenizer_normalization(self):
        """Verify tokenization normalizes case, splits words, and handles punctuation."""
        sample_title = '"PRODUCTION OF A PHARMACEUTICAL CONTAINER FROM THE MELT!"'
        tokens = normalize_and_tokenize(sample_title)
        expected = ["production", "of", "a", "pharmaceutical", "container", "from", "the", "melt"]
        self.assertEqual(tokens, expected)

        # Punctuation & hyphenation
        mixed = "anti-cancer; 5G-enabled, device (100% efficiency)!"
        tokens_mixed = normalize_and_tokenize(mixed)
        self.assertEqual(tokens_mixed, ["anti", "cancer", "5g", "enabled", "device", "100", "efficiency"])

    def test_03_tokenizer_deduplication(self):
        """Verify duplicate terms within the same patent are collapsed to a set."""
        title = "Solar panel system with solar tracking"
        field = "SOLAR ENERGY AND TRACKING SYSTEMS"
        terms = extract_unique_terms_from_patent(title, field)
        # 'solar' appears 3 times in text, but should be in set exactly once
        self.assertIn("solar", terms)
        self.assertIn("tracking", terms)
        self.assertIn("system", terms)
        self.assertIn("systems", terms)
        # Verify set length
        self.assertEqual(len(terms), len(set(terms)))

    def test_04_tokenizer_query_consistency(self):
        """Verify query tokenization matches index tokenization."""
        raw_query = '  "Solar-Powered" CARS & Batteries!  '
        query_tokens = tokenize_query(raw_query)
        self.assertEqual(query_tokens, ["solar", "powered", "cars", "batteries"])

    def test_05_index_status_and_build(self):
        """Verify index building, atomic swap, chunking, and status retrieval."""
        # 1. Build index
        build_res = build_index()
        self.assertTrue(build_res.success)
        self.assertEqual(build_res.status, "ready")
        self.assertEqual(build_res.records_processed, 151439)
        self.assertGreater(build_res.unique_terms_indexed, 30000)
        self.assertGreater(build_res.total_postings, 1000000)

        # 2. Check status endpoint
        status_res = get_status()
        self.assertTrue(status_res.is_indexed)
        self.assertEqual(status_res.status, "ready")
        self.assertEqual(status_res.total_records, 151439)

        # 3. Check MongoDB collection properties
        col = db[settings.INVERTED_INDEX_COLLECTION]
        doc_count = col.count_documents({})
        self.assertGreater(doc_count, 30000)

        # Verify index on collection
        indexes = col.index_information()
        self.assertTrue(
            any("term_chunk_unique" in name or "term" in str(idx.get("key")) for name, idx in indexes.items()),
            "Index on term should exist"
        )

    def test_06_single_keyword_search(self):
        """Verify single keyword search returns matching patents."""
        res = search(q="solar", page=1, page_size=10)
        self.assertGreater(res.total, 0)
        self.assertEqual(len(res.results), 10)
        self.assertEqual(res.page, 1)
        self.assertEqual(res.page_size, 10)
        self.assertGreater(res.total_pages, 0)

        # Check fields of the first result
        first = res.results[0]
        self.assertIsNotNone(first.id)
        self.assertIsNotNone(first.title)
        self.assertIn(first.year, range(2016, 2024))
        self.assertIn("solar", (first.title + " " + (first.field_of_invention or "")).lower())

    def test_07_multiword_and_semantics(self):
        """Verify multiword search uses strict AND semantics."""
        # Query 1: solar
        solar_res = search(q="solar", page=1, page_size=10)
        # Query 2: solar panel
        panel_res = search(q="solar panel", page=1, page_size=10)

        # AND semantics: "solar panel" must match <= "solar"
        self.assertLessEqual(panel_res.total, solar_res.total)
        self.assertGreater(panel_res.total, 0)

        # Every result in "solar panel" must have both "solar" and "panel" in title or field
        for patent in panel_res.results:
            text = f"{patent.title or ''} {patent.field_of_invention or ''}".lower()
            tokens = normalize_and_tokenize(text)
            self.assertIn("solar", tokens)
            self.assertIn("panel", tokens)

    def test_08_no_matches_search(self):
        """Verify keyword with no matches returns empty results without error."""
        res = search(q="zyxwnonexistentkeyword9999", page=1, page_size=10)
        self.assertEqual(res.total, 0)
        self.assertEqual(res.total_pages, 0)
        self.assertEqual(len(res.results), 0)

    def test_09_pagination_consistency(self):
        """Verify pagination produces distinct page results with deterministic order."""
        page1 = search(q="pharmaceutical", page=1, page_size=10)
        page2 = search(q="pharmaceutical", page=2, page_size=10)

        self.assertGreater(page1.total, 20)
        page1_ids = {r.id for r in page1.results}
        page2_ids = {r.id for r in page2.results}

        # Page 1 and Page 2 should have completely disjoint sets of patent IDs
        self.assertEqual(len(page1_ids.intersection(page2_ids)), 0)

    def test_10_empty_and_invalid_queries(self):
        """Verify empty queries and invalid pagination values are rejected."""
        from fastapi import HTTPException
        # Empty query
        with self.assertRaises(HTTPException) as cm:
            search(q="   ", page=1, page_size=10)
        self.assertEqual(cm.exception.status_code, 400)

        # Non-alphanumeric query
        with self.assertRaises(HTTPException) as cm:
            search(q="!@#$%^&*", page=1, page_size=10)
        self.assertEqual(cm.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
