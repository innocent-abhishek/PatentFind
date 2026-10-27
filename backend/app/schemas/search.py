from typing import List, Optional
from pydantic import BaseModel, Field


class PatentResultItem(BaseModel):
    id: str = Field(..., description="Unique record ObjectId string")
    year: int = Field(..., description="Year of the patent collection (e.g. 2016)")
    collection: str = Field(..., description="Source collection name (e.g. patents_2016)")
    publication_number: Optional[str] = Field(None, description="Patent publication number")
    publication_date: Optional[str] = Field(None, description="Publication date string")
    title: Optional[str] = Field(None, description="Title of invention")
    field_of_invention: Optional[str] = Field(None, description="Field of invention")
    application_number: Optional[str] = Field(None, description="Application number")
    application_type: Optional[str] = Field(None, description="Application type description")
    date_of_filing: Optional[str] = Field(None, description="Filing date string")
    ipo_location: Optional[str] = Field(None, description="IPO location")
    no_of_claims: Optional[int] = Field(None, description="Number of claims (count only)")
    no_of_pages: Optional[int] = Field(None, description="Number of pages")


class SearchResponse(BaseModel):
    query: str = Field(..., description="Raw search query string")
    query_terms: List[str] = Field(..., description="Normalized tokens used for searching")
    total: int = Field(..., description="Total matching patent records across all collections")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of results per page")
    total_pages: int = Field(..., description="Total available pages")
    execution_time_ms: float = Field(..., description="Search execution duration in milliseconds")
    results: List[PatentResultItem] = Field(default_factory=list, description="List of matching patent records for current page")
