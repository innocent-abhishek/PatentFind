import logging
from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import require_admin
from app.indexing.indexer import build_inverted_index, get_index_status
from app.schemas.index import IndexBuildResponse, IndexStatusResponse

logger = logging.getLogger("patentfind.api.index")
router = APIRouter(prefix="/index", tags=["Index Management"])


@router.get("/status", response_model=IndexStatusResponse, summary="Get inverted index status")
def get_status() -> IndexStatusResponse:
    """
    Returns the current status of the persistent inverted index,
    including build state, total records indexed, unique term count,
    and the timestamp of the last successful build.
    """
    try:
        return get_index_status()
    except Exception as exc:
        logger.error("Error retrieving index status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve index status."
        )


@router.post(
    "/build",
    response_model=IndexBuildResponse,
    status_code=status.HTTP_200_OK,
    summary="Build or rebuild the persistent inverted index",
    dependencies=[Depends(require_admin)]
)
def build_index(current_admin: dict = Depends(require_admin)) -> IndexBuildResponse:
    """
    Triggers construction or rebuilding of the persistent inverted index
    across all patent collections (2016-2023).

    Protections:
    - Prevents overlapping simultaneous builds (returns 409 Conflict).
    - Uses an atomic collection swap (rename) so active searches remain unaffected
      and failed builds do not corrupt the working index.
    """
    try:
        return build_inverted_index()
    except RuntimeError as exc:
        err_msg = str(exc)
        if "already in progress" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Index construction failed: {err_msg}"
        )
    except Exception as exc:
        logger.error("Unhandled error during index build: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during index construction."
        )
