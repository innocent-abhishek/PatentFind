import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from app.core.config import settings
from app.db.mongodb import db
from app.indexing.tokenizer import extract_unique_terms_from_patent
from app.schemas.index import IndexBuildResponse, IndexStatusResponse

logger = logging.getLogger("patentfind.indexer")

# Thread lock to guarantee that only one rebuild can execute at a time
_build_lock = threading.Lock()


def get_index_status() -> IndexStatusResponse:
    """
    Retrieves the current status of the inverted index.
    Checks both the metadata collection and the physical existence of the index collection.
    """
    col_names = db.list_collection_names()
    has_index_col = settings.INVERTED_INDEX_COLLECTION in col_names
    
    meta_doc = db[settings.METADATA_COLLECTION].find_one({"_id": "index_status"})
    
    if not meta_doc or not has_index_col:
        return IndexStatusResponse(
            status="not_built",
            is_indexed=False,
            total_records=0,
            unique_terms=0,
            total_postings=0,
            last_built_at=None,
            build_duration_seconds=None,
            collections_indexed=[],
            message="Inverted index has not been built yet. Please trigger an index build."
        )
        
    status = meta_doc.get("status", "unknown")
    is_indexed = (status == "ready") and has_index_col
    
    return IndexStatusResponse(
        status=status,
        is_indexed=is_indexed,
        total_records=meta_doc.get("total_records"),
        unique_terms=meta_doc.get("unique_terms"),
        total_postings=meta_doc.get("total_postings"),
        last_built_at=meta_doc.get("last_built_at"),
        build_duration_seconds=meta_doc.get("build_duration_seconds"),
        collections_indexed=meta_doc.get("collections_indexed", []),
        message=meta_doc.get("message")
    )


def build_inverted_index() -> IndexBuildResponse:
    """
    Builds or rebuilds the persistent inverted index from patent collections 2016-2023.
    
    Features:
    - Safe concurrency: prevents overlapping builds via thread locking.
    - Safe rebuild strategy: builds into a temporary collection and atomically swaps it
      into service via collection rename (dropTarget=True).
    - 16MB document size protection: chunks postings into documents with max POSTINGS_CHUNK_SIZE items.
    - Zero duplicates: each patent ID appears at most once per term posting list.
    - Memory efficient: uses field projections so only needed fields are streamed.
    - Non-destructive: leaves original patent collections unchanged.
    """
    acquired = _build_lock.acquire(blocking=False)
    if not acquired:
        logger.warning("Attempted to start an index build while another build is in progress.")
        raise RuntimeError("An index build operation is already in progress. Please wait for it to complete.")

    start_time = time.time()
    temp_col = db[settings.TEMP_INDEX_COLLECTION]
    meta_col = db[settings.METADATA_COLLECTION]

    try:
        logger.info("Starting inverted index build across collections: %s", settings.PATENT_COLLECTIONS)
        
        # Mark status as building in metadata
        meta_col.update_one(
            {"_id": "index_status"},
            {
                "$set": {
                    "status": "building",
                    "build_started_at": datetime.now(timezone.utc).isoformat(),
                    "message": "Index construction is in progress..."
                }
            },
            upsert=True
        )

        # 1. Read patent records from all 8 collections and accumulate postings
        # Mapping: term -> list of (year: int, doc_id: ObjectId)
        index_map = defaultdict(list)
        records_processed = 0

        for year in settings.PATENT_YEARS:
            col_name = f"patents_{year}"
            col = db[col_name]
            # Projection ensures we only load required fields, keeping memory low
            cursor = col.find(
                {},
                {"_id": 1, "TITLE_OF_INVENTION": 1, "FIELD_OF_INVENTION": 1}
            )
            col_count = 0
            for doc in cursor:
                records_processed += 1
                col_count += 1
                doc_id = doc["_id"]
                terms = extract_unique_terms_from_patent(
                    doc.get("TITLE_OF_INVENTION"),
                    doc.get("FIELD_OF_INVENTION")
                )
                for term in terms:
                    index_map[term].append((year, doc_id))
            logger.info("Read %d records from %s", col_count, col_name)

        unique_terms_count = len(index_map)
        total_postings_count = sum(len(postings) for postings in index_map.values())
        logger.info(
            "Completed reading: %d records, %d unique terms, %d total postings",
            records_processed, unique_terms_count, total_postings_count
        )

        # 2. Prepare temporary collection
        temp_col.drop()

        # 3. Chunk postings and bulk insert into temporary collection
        docs_batch = []
        batch_size = settings.BULK_INSERT_BATCH_SIZE
        chunk_size = settings.POSTINGS_CHUNK_SIZE

        for term, postings in index_map.items():
            for chunk_id, i in enumerate(range(0, len(postings), chunk_size)):
                chunk_slice = postings[i:i + chunk_size]
                docs_batch.append({
                    "term": term,
                    "chunk_id": chunk_id,
                    "doc_count": len(chunk_slice),
                    "postings": [{"y": y, "id": doc_id} for y, doc_id in chunk_slice]
                })

                if len(docs_batch) >= batch_size:
                    temp_col.insert_many(docs_batch)
                    docs_batch = []

        if docs_batch:
            temp_col.insert_many(docs_batch)

        # 4. Create compound unique index on (term, chunk_id)
        temp_col.create_index(
            [("term", 1), ("chunk_id", 1)],
            unique=True,
            name="term_chunk_unique"
        )
        # Prefix index for fast term lookups
        temp_col.create_index("term", name="term_index")

        # 5. Atomically swap temporary collection into active service
        logger.info("Atomically swapping %s into %s", settings.TEMP_INDEX_COLLECTION, settings.INVERTED_INDEX_COLLECTION)
        temp_col.rename(settings.INVERTED_INDEX_COLLECTION, dropTarget=True)

        elapsed = round(time.time() - start_time, 2)
        success_message = (
            f"Successfully built inverted index with {records_processed:,} records, "
            f"{unique_terms_count:,} unique terms, and {total_postings_count:,} postings in {elapsed}s."
        )

        # 6. Update metadata collection with success status
        meta_col.update_one(
            {"_id": "index_status"},
            {
                "$set": {
                    "status": "ready",
                    "is_indexed": True,
                    "total_records": records_processed,
                    "unique_terms": unique_terms_count,
                    "total_postings": total_postings_count,
                    "last_built_at": datetime.now(timezone.utc).isoformat(),
                    "build_duration_seconds": elapsed,
                    "collections_indexed": settings.PATENT_COLLECTIONS,
                    "message": success_message
                }
            },
            upsert=True
        )

        logger.info(success_message)

        return IndexBuildResponse(
            success=True,
            status="ready",
            records_processed=records_processed,
            unique_terms_indexed=unique_terms_count,
            total_postings=total_postings_count,
            elapsed_time_seconds=elapsed,
            message=success_message
        )

    except Exception as exc:
        elapsed = round(time.time() - start_time, 2)
        err_msg = f"Index build failed: {str(exc)}"
        logger.error(err_msg, exc_info=True)

        # Safely clean up temporary collection
        try:
            temp_col.drop()
        except Exception:
            pass

        # Update metadata to failed state
        try:
            meta_col.update_one(
                {"_id": "index_status"},
                {
                    "$set": {
                        "status": "failed",
                        "last_failed_at": datetime.now(timezone.utc).isoformat(),
                        "message": err_msg
                    }
                },
                upsert=True
            )
        except Exception:
            pass

        raise RuntimeError(err_msg) from exc

    finally:
        _build_lock.release()
