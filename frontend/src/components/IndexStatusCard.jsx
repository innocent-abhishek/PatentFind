import React from "react";

export default function IndexStatusCard({
  statusData,
  isStatusLoading,
  isBuilding,
  buildMessage,
  onBuild,
  onRefresh,
}) {
  const isIndexed = statusData?.is_indexed;
  const status = statusData?.status || "unknown";

  const getStatusBadge = () => {
    if (isBuilding || status === "building") {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse"></span>
          Building Index...
        </span>
      );
    }
    if (isIndexed && status === "ready") {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300">
          <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
          Index Ready
        </span>
      );
    }
    if (status === "failed") {
      return (
        <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300">
          <span className="w-2 h-2 rounded-full bg-rose-500"></span>
          Build Failed
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-700 border border-slate-300">
        <span className="w-2 h-2 rounded-full bg-slate-400"></span>
        Not Built
      </span>
    );
  };

  const formatDate = (isoStr) => {
    if (!isoStr) return "Never";
    try {
      return new Date(isoStr).toLocaleString();
    } catch {
      return isoStr;
    }
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs mb-8 transition-all">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-semibold text-slate-800">Inverted Index Status</h2>
            {getStatusBadge()}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Persistent index stored in MongoDB collection{" "}
            <code className="text-slate-700 font-mono bg-slate-100 px-1.5 py-0.5 rounded">
              inverted_index
            </code>
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onRefresh}
            disabled={isStatusLoading || isBuilding}
            className="px-3 py-2 text-xs font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 disabled:opacity-50 rounded-lg transition-colors cursor-pointer"
            title="Refresh index status"
          >
            {isStatusLoading ? "Checking..." : "Refresh"}
          </button>

          <button
            type="button"
            onClick={onBuild}
            disabled={isBuilding}
            className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 rounded-lg shadow-xs transition-colors flex items-center gap-2 cursor-pointer"
          >
            {isBuilding ? (
              <>
                <svg
                  className="animate-spin h-3.5 w-3.5 text-white"
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
                Building Index...
              </>
            ) : isIndexed ? (
              "Rebuild Index"
            ) : (
              "Build Index"
            )}
          </button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 pt-4 text-center sm:text-left">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Indexed Records</span>
          <p className="text-xl font-bold text-slate-800 mt-0.5">
            {statusData?.total_records ? Number(statusData.total_records).toLocaleString() : "0"}
          </p>
          <span className="text-[11px] text-slate-400">patents (2016-2023)</span>
        </div>

        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Unique Terms</span>
          <p className="text-xl font-bold text-slate-800 mt-0.5">
            {statusData?.unique_terms ? Number(statusData.unique_terms).toLocaleString() : "0"}
          </p>
          <span className="text-[11px] text-slate-400">vocabulary size</span>
        </div>

        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Total Postings</span>
          <p className="text-xl font-bold text-slate-800 mt-0.5">
            {statusData?.total_postings ? Number(statusData.total_postings).toLocaleString() : "0"}
          </p>
          <span className="text-[11px] text-slate-400">term-document links</span>
        </div>

        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wider font-medium">Last Built</span>
          <p className="text-sm font-semibold text-slate-700 mt-1 truncate" title={formatDate(statusData?.last_built_at)}>
            {formatDate(statusData?.last_built_at)}
          </p>
          <span className="text-[11px] text-slate-400">
            {statusData?.build_duration_seconds ? `Duration: ${statusData.build_duration_seconds}s` : ""}
          </span>
        </div>
      </div>

      {/* Build Message Banner */}
      {buildMessage && (
        <div
          className={`mt-4 p-3 rounded-lg text-xs flex items-center justify-between ${
            buildMessage.type === "error"
              ? "bg-rose-50 border border-rose-200 text-rose-800"
              : "bg-emerald-50 border border-emerald-200 text-emerald-800"
          }`}
        >
          <span>{buildMessage.text}</span>
        </div>
      )}
    </div>
  );
}
