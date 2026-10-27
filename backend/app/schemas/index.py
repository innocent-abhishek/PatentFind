from typing import List, Optional
from pydantic import BaseModel, Field


class IndexStatusResponse(BaseModel):
    status: str = Field(..., description="Current index status: ready, building, not_built, or failed")
    is_indexed: bool = Field(..., description="Whether a valid, searchable inverted index exists")
    total_records: Optional[int] = Field(None, description="Total patent records indexed")
    unique_terms: Optional[int] = Field(None, description="Number of unique terms in the index")
    total_postings: Optional[int] = Field(None, description="Total postings count across all terms")
    last_built_at: Optional[str] = Field(None, description="ISO timestamp of the last successful build")
    build_duration_seconds: Optional[float] = Field(None, description="Duration in seconds of the last build")
    collections_indexed: Optional[List[str]] = Field(None, description="List of MongoDB collections included in the index")
    message: Optional[str] = Field(None, description="Informational message or error description")


class IndexBuildResponse(BaseModel):
    success: bool = Field(..., description="Whether index construction completed successfully")
    status: str = Field(..., description="Index status after build operation")
    records_processed: int = Field(..., description="Total patent records read and indexed")
    unique_terms_indexed: int = Field(..., description="Total unique normalized terms in the index")
    total_postings: int = Field(..., description="Total term-document postings indexed")
    elapsed_time_seconds: float = Field(..., description="Total elapsed time in seconds for the build")
    message: str = Field(..., description="Summary status message")
