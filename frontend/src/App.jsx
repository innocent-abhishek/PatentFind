import React, { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { fetchIndexStatus, triggerBuildIndex, searchPatents } from "./api";
import NavigationHeader from "./components/NavigationHeader";
import LoginPage from "./components/LoginPage";
import RegisterPage from "./components/RegisterPage";
import IndexStatusCard from "./components/IndexStatusCard";
import SearchBar from "./components/SearchBar";
import PatentCard from "./components/PatentCard";
import Pagination from "./components/Pagination";

function MainContent() {
  const { token, isAdmin } = useAuth();
  const [currentView, setCurrentView] = useState("dashboard"); // 'dashboard' | 'login' | 'register'

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

  /**
   * Protected index rebuild: sends the JWT token in Authorization: Bearer <token>.
   * Only administrators are authorized on the backend.
   */
  const handleBuildIndex = async () => {
    if (!isAdmin) {
      setBuildMessage({
        type: "error",
        text: "Administrator privileges required to rebuild the inverted index.",
      });
      return;
    }

    setIsBuilding(true);
    setBuildMessage(null);
    try {
      const res = await triggerBuildIndex(token);
      setBuildMessage({
        type: "success",
        text: res.message || "Inverted index built successfully!",
      });
      await loadStatus();
    } catch (err) {
      let errText = err.message || "Failed to build index.";
      if (err.status === 401) {
        errText = "Authentication expired. Please sign in again as administrator.";
      } else if (err.status === 403) {
        errText = "Access forbidden: Administrator privileges required.";
      }
      setBuildMessage({
        type: "error",
        text: errText,
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
      setSearchError(err.message || "Search execution failed.");
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
    <div className="min-h-screen bg-[#F9F8F6] text-slate-800 flex flex-col font-sans">
      {/* Top Navigation */}
      <NavigationHeader
        currentView={currentView}
        onViewChange={(view) => setCurrentView(view)}
      />

      {/* Main Content Area */}
      <div className="flex-1">
        {currentView === "login" && (
          <LoginPage onNavigate={(view) => setCurrentView(view)} />
        )}

        {currentView === "register" && (
          <RegisterPage onNavigate={(view) => setCurrentView(view)} />
        )}

        {currentView === "dashboard" && (
          <main className="max-w-5xl mx-auto px-4 py-8 sm:px-6">
            {/* Index Status Card (All users see stats, admin sees rebuild control) */}
            <IndexStatusCard
              statusData={statusData}
              isStatusLoading={isStatusLoading}
              isBuilding={isBuilding}
              buildMessage={buildMessage}
              onBuild={handleBuildIndex}
              onRefresh={loadStatus}
            />

            {/* Keyword Search Bar */}
            <SearchBar
              onSearch={(q) => executeSearch(q, 1, pageSize)}
              isSearching={isSearching}
              initialQuery={currentQuery}
              isIndexed={statusData?.is_indexed}
            />

            {/* Search Error Alert */}
            {searchError && (
              <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 mb-6 text-xs text-rose-800 flex items-start gap-2.5">
                <svg
                  className="w-4 h-4 text-rose-600 shrink-0 mt-0.5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth="2"
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
                <div>
                  <p className="font-semibold">Search Error</p>
                  <p className="mt-0.5">{searchError}</p>
                </div>
              </div>
            )}

            {/* Loading Spinner */}
            {isSearching && (
              <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-600 mb-8 shadow-xs">
                <svg
                  className="animate-spin h-7 w-7 text-slate-900 mx-auto mb-3"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                >
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                </svg>
                <p className="text-sm font-semibold text-slate-800">Searching persistent inverted index...</p>
                <p className="text-xs text-slate-400 mt-1">Intersecting postings and retrieving patent metadata</p>
              </div>
            )}

            {/* Search Results Display */}
            {!isSearching && searchResults && (
              <div>
                {/* Results Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3.5 mb-4 border-b border-slate-200">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-bold text-slate-900">
                      {searchResults.total.toLocaleString()} {searchResults.total === 1 ? "result" : "results"}
                    </span>
                    <span className="text-xs text-slate-500">
                      for &ldquo;<strong className="text-slate-800">{searchResults.query}</strong>&rdquo;
                    </span>
                    <span className="text-[11px] text-slate-500 font-mono bg-white border border-slate-200 px-2 py-0.5 rounded">
                      {searchResults.execution_time_ms} ms
                    </span>
                  </div>

                  {searchResults.query_terms && searchResults.query_terms.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-xs text-slate-400">Indexed terms (AND):</span>
                      {searchResults.query_terms.map((term) => (
                        <span
                          key={term}
                          className="px-2 py-0.5 rounded text-[11px] font-mono bg-white text-slate-800 border border-slate-200 font-medium"
                        >
                          +{term}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Empty Results State */}
                {searchResults.total === 0 && (
                  <div className="bg-white border border-slate-200 rounded-xl p-10 text-center text-slate-600 shadow-xs">
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
                    <h3 className="text-base font-semibold text-slate-900 mb-1">
                      No patents found matching all query terms
                    </h3>
                    <p className="text-xs text-slate-500 max-w-md mx-auto">
                      Because PatentFind uses strict multiword AND semantics, all tokens must appear in the
                      Title of Invention or Field of Invention. Try broader keywords.
                    </p>
                  </div>
                )}

                {/* Patent Cards List */}
                {searchResults.results && searchResults.results.length > 0 && (
                  <div className="space-y-3.5">
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
              <div className="bg-white border border-slate-200 rounded-xl p-8 text-center text-slate-500 shadow-xs">
                <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center mx-auto mb-3">
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth="2"
                      d="M8 16l2.879-2.879m0 0a3 3 0 104.243-4.242 3 3 0 00-4.243 4.242zM21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                </div>
                <h3 className="text-base font-bold text-slate-900 mb-1">
                  Ready for Keyword Search
                </h3>
                <p className="text-xs text-slate-500 max-w-lg mx-auto">
                  Search across 151,439 Indian Patent Office (IPO) records spanning 2016 through 2023.
                  Queries match against normalized terms in the Title of Invention and Field of Invention.
                </p>
              </div>
            )}
          </main>
        )}
      </div>

      {/* Footer */}
      <footer className="mt-auto border-t border-slate-200 bg-white py-5 text-center text-xs text-slate-500">
        <p className="font-medium text-slate-700">PatentFind &mdash; Discover. Search. Innovate.</p>
        <p className="text-[11px] text-slate-400 mt-0.5">
          Indian Patent Office (IPO) Research Engine (2016-2023) &bull; Built with FastAPI, MongoDB, React & Tailwind CSS.
        </p>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <MainContent />
    </AuthProvider>
  );
}
