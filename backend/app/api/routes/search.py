import logging
from fastapi import APIRouter, HTTPException, Query, status
from app.schemas.search import SearchResponse
from app.search.searcher import IndexNotReadyException, search_patents

logger = logging.getLogger("patentfind.api.search")
router = APIRouter(tags=["Search"])


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search patents by keyword using the persistent inverted index"
)
def search(
    q: str = Query(..., min_length=1, description="Keyword or short phrase to search"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(10, ge=1, le=100, description="Results per page (1-100)")
) -> SearchResponse:
    """
    Searches patent titles and fields of invention using the persistent inverted index.

    Semantics:
    - Normalizes terms consistently with index tokenization (lowercase, alphanumeric).
    - Multiword queries use strict AND semantics: every query term must match.
    - Slices matching results deterministically and retrieves full metadata for the page.
    """
    clean_query = q.strip()
    if not clean_query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Search query cannot be empty or only whitespace."
        )

    try:
        return search_patents(query=clean_query, page=page, page_size=page_size)
    except IndexNotReadyException as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc)
        )
    except Exception as exc:
        logger.error("Search failed for query '%s': %s", clean_query, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while executing the search."
        )
