import React, { useEffect, useState } from "react";
import { fetchIndexStatus, triggerBuildIndex, searchPatents } from "./api";
import IndexStatusCard from "./components/IndexStatusCard";
import SearchBar from "./components/SearchBar";
import PatentCard from "./components/PatentCard";
import Pagination from "./components/Pagination";

export default function App() {
  // Index Status State
  const [statusData, setStatusData] = useState(null);
  const [isStatusLoading, setIsStatusLoading] = useState(true);
  const [isBuilding, setIsBuilding] = useState(false);
  const [buildMessage, setBuildMessage] = useState(null);

  // Search State
  const [currentQuery, setCurrentQuery] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [searchResults, setSearchResults] = useState(null);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);

  // Load status on mount
  useEffect(() => {
    loadStatus();
  }, []);

  const loadStatus = async () => {
    setIsStatusLoading(true);
    try {
      const data = await fetchIndexStatus();
      setStatusData(data);
    } catch (err) {
      console.error("Failed to load index status:", err);
    } finally {
      setIsStatusLoading(false);
    }
  };

  const handleBuildIndex = async () => {
    setIsBuilding(true);
    setBuildMessage(null);
    try {
      const res = await triggerBuildIndex();
      setBuildMessage({
        type: "success",
        text: res.message || "Inverted index built successfully!",
      });
      await loadStatus();
    } catch (err) {
      setBuildMessage({
        type: "error",
        text: err.message || "Failed to build index.",
      });
    } finally {
      setIsBuilding(false);
    }
  };

  const executeSearch = async (queryText, page = 1, size = pageSize) => {
    if (!queryText.trim()) return;

    setIsSearching(true);
    setSearchError(null);
    setCurrentQuery(queryText);
    setCurrentPage(page);

    try {
      const data = await searchPatents(queryText, page, size);
      setSearchResults(data);
    } catch (err) {
      console.error("Search error:", err);
      setSearchError(err.message || "Search failed.");
      setSearchResults(null);
    } finally {
      setIsSearching(false);
    }
  };

  const handlePageChange = (newPage) => {
    if (newPage >= 1 && currentQuery) {
      executeSearch(currentQuery, newPage, pageSize);
      window.scrollTo({ top: 300, behavior: "smooth" });
    }
  };

  const handlePageSizeChange = (newSize) => {
    setPageSize(newSize);
    if (currentQuery) {
      executeSearch(currentQuery, 1, newSize);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      {/* Top Header */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-2xs">
        <div className="max-w-5xl mx-auto px-4 py-4 sm:px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 text-white flex items-center justify-center font-bold text-lg shadow-xs">
              P
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-slate-900 leading-tight">
                PatentFind
              </h1>
              <p className="text-xs text-slate-500 font-medium">
                Phase 2: Persistent Inverted Index & Keyword Search
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className="hidden sm:inline-block px-2.5 py-1 rounded bg-slate-100 text-slate-600 font-medium">
              151,439 Patents (2016-2023)
            </span>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="max-w-5xl mx-auto px-4 py-8 sm:px-6">
        {/* Index Status Card */}
        <IndexStatusCard
          statusData={statusData}
          isStatusLoading={isStatusLoading}
          isBuilding={isBuilding}
          buildMessage={buildMessage}
          onBuild={handleBuildIndex}
          onRefresh={loadStatus}
        />

        {/* Search Bar */}
        <SearchBar
          onSearch={(q) => executeSearch(q, 1, pageSize)}
          isSearching={isSearching}
          initialQuery={currentQuery}
          isIndexed={statusData?.is_indexed}
        />

        {/* Search Error Alert */}
        {searchError && (
          <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 mb-6 text-sm text-rose-800 flex items-start gap-3">
            <svg
              className="w-5 h-5 text-rose-500 shrink-0 mt-0.5"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z"
                clipRule="evenodd"
              />
            </svg>
            <div>
              <p className="font-semibold">Search Error</p>
              <p className="mt-1 text-xs">{searchError}</p>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isSearching && (
          <div className="space-y-4 mb-8">
            <div className="text-center py-10 text-slate-500">
              <svg
                className="animate-spin h-8 w-8 text-indigo-600 mx-auto mb-3"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                ></circle>
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8v8H4z"
                ></path>
              </svg>
              <p className="text-sm font-medium text-slate-700">Looking up keywords in inverted index...</p>
              <p className="text-xs text-slate-400 mt-1">Intersecting postings and fetching metadata</p>
            </div>
          </div>
        )}

        {/* Search Results */}
        {!isSearching && searchResults && (
          <div>
            {/* Results Header */}
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-4 mb-4 border-b border-slate-200">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-slate-900">
                  {searchResults.total.toLocaleString()} {searchResults.total === 1 ? "result" : "results"}
                </span>
                <span className="text-xs text-slate-500">
                  for &ldquo;<strong className="text-slate-800">{searchResults.query}</strong>&rdquo;
                </span>
                <span className="text-[11px] text-slate-400 font-mono bg-slate-100 px-2 py-0.5 rounded">
                  {searchResults.execution_time_ms} ms
                </span>
              </div>

              {searchResults.query_terms && searchResults.query_terms.length > 0 && (
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs text-slate-400">Indexed terms (AND):</span>
                  {searchResults.query_terms.map((term) => (
                    <span
                      key={term}
                      className="px-2 py-0.5 rounded text-[11px] font-mono bg-indigo-50 text-indigo-700 border border-indigo-200"
                    >
                      +{term}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* Empty Results State */}
            {searchResults.total === 0 && (
              <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-600">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                </div>
                <h3 className="text-base font-semibold text-slate-800 mb-1">
                  No patents found matching all query terms
                </h3>
                <p className="text-xs text-slate-500 max-w-md mx-auto">
                  Because this phase uses strict AND semantics, every word in your query must appear
                  in the Title of Invention or Field of Invention. Try fewer terms or common keywords.
                </p>
              </div>
            )}

            {/* Results List */}
            {searchResults.results && searchResults.results.length > 0 && (
              <div className="space-y-4">
                {searchResults.results.map((patent, idx) => (
                  <PatentCard key={patent.id || idx} patent={patent} index={idx} />
                ))}

                {/* Pagination Controls */}
                <Pagination
                  currentPage={searchResults.page}
                  totalPages={searchResults.total_pages}
                  totalResults={searchResults.total}
                  pageSize={searchResults.page_size}
                  onPageChange={handlePageChange}
                  onPageSizeChange={handlePageSizeChange}
                  isLoading={isSearching}
                />
              </div>
            )}
          </div>
        )}

        {/* Initial Empty State before search */}
        {!isSearching && !searchResults && !searchError && (
          <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500">
            <div className="w-12 h-12 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="2"
                  d="M8 16l2.879-2.879m0 0a3 3 0 104.243-4.242 3 3 0 00-4.243 4.242zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            </div>
            <h3 className="text-base font-semibold text-slate-800 mb-1">
              Ready for Keyword Search
            </h3>
            <p className="text-xs text-slate-500 max-w-lg mx-auto">
              Search over 151,439 patents across Indian Patent Office (IPO) records from 2016 to 2023.
              Search matches against normalized tokens in the patent title and field of invention.
            </p>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="mt-16 border-t border-slate-200 bg-white py-6 text-center text-xs text-slate-400">
        PatentFind &mdash; Phase 2: Inverted Index & Keyword Search &mdash; Fast, deterministic, keyword-driven patent discovery.
      </footer>
    </div>
  );
}
