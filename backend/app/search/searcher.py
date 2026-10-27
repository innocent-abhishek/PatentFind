import math
import time
from collections import defaultdict
from typing import Dict, List, Set, Tuple
from bson import ObjectId

from app.core.config import settings
from app.db.mongodb import db
from app.indexing.indexer import get_index_status
from app.indexing.tokenizer import tokenize_query
from app.schemas.search import PatentResultItem, SearchResponse


class IndexNotReadyException(Exception):
    """Raised when search is executed before the index is built."""
    pass


def search_patents(query: str, page: int = 1, page_size: int = 10) -> SearchResponse:
    """
    Executes keyword search using the persistent inverted index in MongoDB.

    Rules:
    - Normalizes query terms using the exact same tokenizer as indexing.
    - Uses strict AND semantics for multiword queries: only patents containing
      all query terms in their TITLE_OF_INVENTION or FIELD_OF_INVENTION are returned.
    - Deterministic ordering: sorted by collection year descending, then record ID descending.
    - Only retrieves full patent metadata for the specific page being requested.
    - Never falls back to full collection scans.
    """
    start_time = time.time()

    # 1. Verify index readiness
    status = get_index_status()
    if not status.is_indexed:
        raise IndexNotReadyException(
            "The inverted index has not been built yet. "
            "Please build the index first via POST /api/index/build."
        )

    # 2. Tokenize query
    query_terms = tokenize_query(query)
    if not query_terms:
        raise ValueError("Search query cannot be empty or contain only non-alphanumeric characters.")

    if page < 1:
        raise ValueError("Page number must be at least 1.")
    if page_size < 1 or page_size > 100:
        raise ValueError("Page size must be between 1 and 100.")

    # 3. Retrieve postings for each query term from the inverted_index collection
    # Optimization: sort by smallest posting set to minimize intersection work
    term_postings_sets: List[Set[Tuple[int, ObjectId]]] = []

    for term in query_terms:
        # Find all chunks for this term
        cursor = db[settings.INVERTED_INDEX_COLLECTION].find(
            {"term": term},
            {"postings": 1, "_id": 0}
        )
        term_postings: Set[Tuple[int, ObjectId]] = set()
        for chunk_doc in cursor:
            for p in chunk_doc.get("postings", []):
                term_postings.add((p["y"], p["id"]))

        # If any query term has 0 postings, AND intersection is definitely empty
        if not term_postings:
            elapsed_ms = round((time.time() - start_time) * 1000, 2)
            return SearchResponse(
                query=query,
                query_terms=query_terms,
                total=0,
                page=page,
                page_size=page_size,
                total_pages=0,
                execution_time_ms=elapsed_ms,
                results=[]
            )

        term_postings_sets.append(term_postings)

    # 4. Multiword AND semantics: intersection across all terms
    # Sort sets by length ascending to optimize set intersection speed
    term_postings_sets.sort(key=len)
    matching_postings = term_postings_sets[0]
    for other_set in term_postings_sets[1:]:
        matching_postings = matching_postings.intersection(other_set)
        if not matching_postings:
            break

    total_matches = len(matching_postings)
    total_pages = math.ceil(total_matches / page_size) if total_matches > 0 else 0

    if total_matches == 0:
        elapsed_ms = round((time.time() - start_time) * 1000, 2)
        return SearchResponse(
            query=query,
            query_terms=query_terms,
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
            execution_time_ms=elapsed_ms,
            results=[]
        )

    # 5. Deterministic sorting: Year descending, then ObjectId string descending
    # This provides a stable, reproducible order across page requests without relevance ranking
    sorted_postings = sorted(
        matching_postings,
        key=lambda item: (item[0], str(item[1])),
        reverse=True
    )

    # 6. Pagination slice
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_slice = sorted_postings[start_idx:end_idx]

    # 7. Fetch matching patent metadata from original MongoDB collections
    # Group IDs by year collection to minimize roundtrips
    ids_by_year: Dict[int, List[ObjectId]] = defaultdict(list)
    for year, doc_id in page_slice:
        ids_by_year[year].append(doc_id)

    # Query original collections
    metadata_cache: Dict[Tuple[int, str], dict] = {}
    for year, doc_ids in ids_by_year.items():
        col_name = f"patents_{year}"
        raw_docs = db[col_name].find({"_id": {"$in": doc_ids}})
        for d in raw_docs:
            metadata_cache[(year, str(d["_id"]))] = d

    # 8. Assemble results in the exact deterministic order of page_slice
    results: List[PatentResultItem] = []
    for year, doc_id in page_slice:
        doc = metadata_cache.get((year, str(doc_id)))
        if not doc:
            continue

        def safe_str(val):
            return str(val) if val is not None else None

        def safe_int(val):
            if val is None:
                return None
            try:
                return int(val)
            except (ValueError, TypeError):
                return None

        results.append(
            PatentResultItem(
                id=str(doc.get("_id")),
                year=year,
                collection=f"patents_{year}",
                publication_number=safe_str(doc.get("PUBLICATION_NUMBER")),
                publication_date=safe_str(doc.get("PUBLICATION_DATE")),
                title=safe_str(doc.get("TITLE_OF_INVENTION")),
                field_of_invention=safe_str(doc.get("FIELD_OF_INVENTION")),
                application_number=safe_str(doc.get("APPLICATION_NUMBER")),
                application_type=safe_str(doc.get("APPLICATION_TYPE_DESC")),
                date_of_filing=safe_str(doc.get("DATE_OF_FILING")),
                ipo_location=safe_str(doc.get("IPO_LOCATION")),
                no_of_claims=safe_int(doc.get("NO_OF_CLAIMS")),
                no_of_pages=safe_int(doc.get("NO_OF_PAGES")),
            )
        )

    elapsed_ms = round((time.time() - start_time) * 1000, 2)

    return SearchResponse(
        query=query,
        query_terms=query_terms,
        total=total_matches,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        execution_time_ms=elapsed_ms,
        results=results
    )
