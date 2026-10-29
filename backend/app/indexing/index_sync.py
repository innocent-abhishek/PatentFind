import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any
from bson import ObjectId
from pymongo.database import Database

from app.core.config import settings
from app.db.mongodb import db
from app.indexing.tokenizer import extract_unique_terms_from_patent

logger = logging.getLogger("patentfind.index_sync")

SYNC_LOG_COLLECTION = "index_sync_log"


def _add_term_posting(
    idx_col,
    term: str,
    year: int,
    doc_id: ObjectId
) -> bool:
    """
    Adds a posting {"y": year, "id": doc_id} for a term.
    Handles chunking (< POSTINGS_CHUNK_SIZE), prevents duplicate postings,
    and returns True if a brand new term was added to the index.
    """
    # 1. Prevent duplicate postings: check if posting already exists
    existing = idx_col.find_one(
        {"term": term, "postings.id": doc_id},
        {"_id": 1, "postings.$": 1}
    )
    if existing:
        matched = existing.get("postings", [])
        if matched and matched[0].get("y") != year:
            # Update year in existing posting if it changed
            idx_col.update_one(
                {"_id": existing["_id"], "postings.id": doc_id},
                {"$set": {"postings.$.y": year}}
            )
        return False

    is_new_term = False

    # 2. Find the last chunk for this term with available capacity
    chunk = idx_col.find_one(
        {"term": term, "doc_count": {"$lt": settings.POSTINGS_CHUNK_SIZE}},
        sort=[("chunk_id", -1)]
    )

    if chunk:
        idx_col.update_one(
            {"_id": chunk["_id"]},
            {
                "$push": {"postings": {"y": year, "id": doc_id}},
                "$inc": {"doc_count": 1}
            }
        )
    else:
        # Check if term has any chunks at all
        last_chunk = idx_col.find_one({"term": term}, sort=[("chunk_id", -1)])
        if last_chunk:
            new_chunk_id = last_chunk.get("chunk_id", 0) + 1
        else:
            new_chunk_id = 0
            is_new_term = True

        new_chunk_doc = {
            "term": term,
            "chunk_id": new_chunk_id,
            "doc_count": 1,
            "postings": [{"y": year, "id": doc_id}]
        }
        idx_col.insert_one(new_chunk_doc)

    return is_new_term


def _remove_term_posting(
    idx_col,
    term: str,
    doc_id: ObjectId
) -> bool:
    """
    Removes the posting for doc_id from the specified term.
    Deletes the chunk if it becomes empty.
    Returns True if the term was completely removed from the index.
    """
    chunks = list(idx_col.find({"term": term, "postings.id": doc_id}))
    if not chunks:
        return False

    for chunk in chunks:
        postings = [p for p in chunk.get("postings", []) if p.get("id") != doc_id]
        if not postings:
            # Chunk is empty, delete it
            idx_col.delete_one({"_id": chunk["_id"]})
        else:
            idx_col.update_one(
                {"_id": chunk["_id"]},
                {"$set": {"postings": postings, "doc_count": len(postings)}}
            )

    # Check if any chunks remain for this term
    remaining_chunks = idx_col.count_documents({"term": term})
    return remaining_chunks == 0


def _update_metadata_counts(
    meta_col,
    records_delta: int,
    postings_delta: int,
    terms_delta: int
) -> None:
    """Incrementally updates index_metadata counters with safe initialization."""
    now_iso = datetime.now(timezone.utc).isoformat()
    meta_col.update_one(
        {"_id": "index_status"},
        {
            "$inc": {
                "total_records": records_delta,
                "total_postings": postings_delta,
                "unique_terms": terms_delta
            },
            "$set": {
                "last_updated_at": now_iso
            },
            "$setOnInsert": {
                "status": "ready",
                "is_indexed": True,
                "collections_indexed": settings.PATENT_COLLECTIONS,
                "last_built_at": now_iso,
                "message": "Index ready with incremental synchronization."
            }
        },
        upsert=True
    )


def sync_index_patent_created(
    patent_doc: dict,
    year: int,
    target_db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Incrementally synchronizes the inverted index when a new patent is created.
    - Tokenizes TITLE_OF_INVENTION and FIELD_OF_INVENTION.
    - Appends postings to inverted_index collection.
    - Increments metadata counts.
    - Logs sync operation for audit/reconciliation.
    """
    database = target_db if target_db is not None else db
    idx_col = database[settings.INVERTED_INDEX_COLLECTION]
    meta_col = database[settings.METADATA_COLLECTION]
    sync_log = database[SYNC_LOG_COLLECTION]

    doc_id = patent_doc["_id"]
    if isinstance(doc_id, str):
        doc_id = ObjectId(doc_id)

    title = patent_doc.get("TITLE_OF_INVENTION")
    field = patent_doc.get("FIELD_OF_INVENTION")
    terms = extract_unique_terms_from_patent(title, field)

    log_entry = {
        "operation": "create",
        "patent_id": doc_id,
        "collection": f"patents_{year}",
        "year": year,
        "terms_count": len(terms),
        "status": "in_progress",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    log_id = sync_log.insert_one(log_entry).inserted_id

    try:
        new_terms_count = 0
        added_postings_count = 0

        for term in terms:
            is_new = _add_term_posting(idx_col, term, year, doc_id)
            if is_new:
                new_terms_count += 1
            added_postings_count += 1

        _update_metadata_counts(
            meta_col,
            records_delta=1,
            postings_delta=added_postings_count,
            terms_delta=new_terms_count
        )

        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
        )

        logger.info(
            "Incremental index sync (create) for patent %s: added %d postings, %d new terms",
            doc_id, added_postings_count, new_terms_count
        )
        return {
            "success": True,
            "terms_indexed": len(terms),
            "new_terms": new_terms_count,
            "postings_added": added_postings_count
        }

    except Exception as exc:
        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "failed", "error": str(exc)}}
        )
        logger.error("Failed incremental index sync for created patent %s: %s", doc_id, exc, exc_info=True)
        raise RuntimeError(f"Index synchronization failed for created patent: {str(exc)}") from exc


def sync_index_patent_updated(
    old_patent_doc: dict,
    new_patent_doc: dict,
    old_year: int,
    new_year: int,
    target_db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Incrementally synchronizes the inverted index when an existing patent is updated.
    - Compares old terms vs new terms.
    - Removes postings for terms no longer present.
    - Adds postings for new terms.
    - If publication year changed, updates posting year for unchanged terms.
    """
    database = target_db if target_db is not None else db
    idx_col = database[settings.INVERTED_INDEX_COLLECTION]
    meta_col = database[settings.METADATA_COLLECTION]
    sync_log = database[SYNC_LOG_COLLECTION]

    doc_id = old_patent_doc["_id"]
    if isinstance(doc_id, str):
        doc_id = ObjectId(doc_id)

    old_terms = extract_unique_terms_from_patent(
        old_patent_doc.get("TITLE_OF_INVENTION"),
        old_patent_doc.get("FIELD_OF_INVENTION")
    )
    new_terms = extract_unique_terms_from_patent(
        new_patent_doc.get("TITLE_OF_INVENTION"),
        new_patent_doc.get("FIELD_OF_INVENTION")
    )

    removed_terms = old_terms - new_terms
    added_terms = new_terms - old_terms
    unchanged_terms = old_terms & new_terms
    year_changed = (old_year != new_year)

    log_entry = {
        "operation": "update",
        "patent_id": doc_id,
        "old_year": old_year,
        "new_year": new_year,
        "removed_terms_count": len(removed_terms),
        "added_terms_count": len(added_terms),
        "year_changed": year_changed,
        "status": "in_progress",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    log_id = sync_log.insert_one(log_entry).inserted_id

    try:
        terms_removed_count = 0
        for term in removed_terms:
            is_deleted = _remove_term_posting(idx_col, term, doc_id)
            if is_deleted:
                terms_removed_count += 1

        terms_added_count = 0
        for term in added_terms:
            is_new = _add_term_posting(idx_col, term, new_year, doc_id)
            if is_new:
                terms_added_count += 1

        # If publication year migrated, update year in all unchanged term postings
        if year_changed:
            for term in unchanged_terms:
                idx_col.update_many(
                    {"term": term, "postings.id": doc_id},
                    {"$set": {"postings.$.y": new_year}}
                )

        postings_delta = len(added_terms) - len(removed_terms)
        terms_delta = terms_added_count - terms_removed_count

        _update_metadata_counts(
            meta_col,
            records_delta=0,
            postings_delta=postings_delta,
            terms_delta=terms_delta
        )

        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
        )

        logger.info(
            "Incremental index sync (update) for patent %s: +%d/-%d terms, year_changed=%s",
            doc_id, len(added_terms), len(removed_terms), year_changed
        )
        return {
            "success": True,
            "terms_added": len(added_terms),
            "terms_removed": len(removed_terms),
            "year_migrated": year_changed
        }

    except Exception as exc:
        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "failed", "error": str(exc)}}
        )
        logger.error("Failed incremental index sync for updated patent %s: %s", doc_id, exc, exc_info=True)
        raise RuntimeError(f"Index synchronization failed for updated patent: {str(exc)}") from exc


def sync_index_patent_deleted(
    patent_doc: dict,
    year: int,
    target_db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Incrementally synchronizes the inverted index when a patent is deleted.
    - Removes all postings for the patent across its indexed terms.
    - Deletes empty chunk documents.
    - Decrements metadata counts.
    """
    database = target_db if target_db is not None else db
    idx_col = database[settings.INVERTED_INDEX_COLLECTION]
    meta_col = database[settings.METADATA_COLLECTION]
    sync_log = database[SYNC_LOG_COLLECTION]

    doc_id = patent_doc["_id"]
    if isinstance(doc_id, str):
        doc_id = ObjectId(doc_id)

    title = patent_doc.get("TITLE_OF_INVENTION")
    field = patent_doc.get("FIELD_OF_INVENTION")
    terms = extract_unique_terms_from_patent(title, field)

    log_entry = {
        "operation": "delete",
        "patent_id": doc_id,
        "collection": f"patents_{year}",
        "year": year,
        "terms_count": len(terms),
        "status": "in_progress",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    log_id = sync_log.insert_one(log_entry).inserted_id

    try:
        terms_deleted_count = 0
        postings_removed_count = 0

        for term in terms:
            is_deleted = _remove_term_posting(idx_col, term, doc_id)
            if is_deleted:
                terms_deleted_count += 1
            postings_removed_count += 1

        _update_metadata_counts(
            meta_col,
            records_delta=-1,
            postings_delta=-postings_removed_count,
            terms_delta=-terms_deleted_count
        )

        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat()}}
        )

        logger.info(
            "Incremental index sync (delete) for patent %s: removed %d postings, %d terms deleted",
            doc_id, postings_removed_count, terms_deleted_count
        )
        return {
            "success": True,
            "postings_removed": postings_removed_count,
            "terms_deleted": terms_deleted_count
        }

    except Exception as exc:
        sync_log.update_one(
            {"_id": log_id},
            {"$set": {"status": "failed", "error": str(exc)}}
        )
        logger.error("Failed incremental index sync for deleted patent %s: %s", doc_id, exc, exc_info=True)
        raise RuntimeError(f"Index synchronization failed for deleted patent: {str(exc)}") from exc


def reconcile_patent_index(
    patent_doc: dict,
    year: int,
    target_db: Optional[Database] = None
) -> Dict[str, Any]:
    """
    Reconciles the inverted index postings for a single patent document.
    Ensures all current terms have postings and any stale postings are cleaned up.
    """
    database = target_db if target_db is not None else db
    idx_col = database[settings.INVERTED_INDEX_COLLECTION]

    doc_id = patent_doc["_id"]
    if isinstance(doc_id, str):
        doc_id = ObjectId(doc_id)

    title = patent_doc.get("TITLE_OF_INVENTION")
    field = patent_doc.get("FIELD_OF_INVENTION")
    expected_terms = extract_unique_terms_from_patent(title, field)

    # 1. Find all postings in the index referencing this patent
    actual_chunks = list(idx_col.find({"postings.id": doc_id}, {"term": 1}))
    actual_terms = {c["term"] for c in actual_chunks}

    # 2. Terms that shouldn't be indexed
    stale_terms = actual_terms - expected_terms
    for term in stale_terms:
        _remove_term_posting(idx_col, term, doc_id)

    # 3. Terms that need to be indexed
    missing_terms = expected_terms - actual_terms
    for term in missing_terms:
        _add_term_posting(idx_col, term, year, doc_id)

    # 4. Verify year for common terms
    for term in (actual_terms & expected_terms):
        _add_term_posting(idx_col, term, year, doc_id)

    return {
        "success": True,
        "patent_id": str(doc_id),
        "stale_terms_removed": len(stale_terms),
        "missing_terms_added": len(missing_terms)
    }
