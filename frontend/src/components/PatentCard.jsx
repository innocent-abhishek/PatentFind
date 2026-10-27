import React from "react";

export default function PatentCard({ patent, index }) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs hover:border-slate-300 transition-all">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
        <div className="flex flex-wrap items-center gap-2">
          {patent.publication_number && (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-semibold bg-slate-900 text-white font-mono">
              Pub #{patent.publication_number}
            </span>
          )}
          {patent.year && (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium bg-slate-100 text-slate-700">
              Year {patent.year}
            </span>
          )}
          {patent.field_of_invention && (
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-medium bg-indigo-50 text-indigo-700 border border-indigo-200">
              {patent.field_of_invention}
            </span>
          )}
        </div>

        {patent.publication_date && (
          <span className="text-xs text-slate-500 font-medium">
            Published: {patent.publication_date}
          </span>
        )}
      </div>

      <h3 className="text-base font-semibold text-slate-900 leading-snug mb-3">
        {patent.title || "Untitled Patent"}
      </h3>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2 pt-3 border-t border-slate-100 text-xs text-slate-600">
        <div>
          <span className="text-slate-400 block text-[11px]">Application No</span>
          <span className="font-mono text-slate-700 truncate block" title={patent.application_number || "N/A"}>
            {patent.application_number || "—"}
          </span>
        </div>

        <div>
          <span className="text-slate-400 block text-[11px]">Application Type</span>
          <span className="text-slate-700 truncate block" title={patent.application_type || "N/A"}>
            {patent.application_type || "—"}
          </span>
        </div>

        <div>
          <span className="text-slate-400 block text-[11px]">Filing Date</span>
          <span className="text-slate-700 block">
            {patent.date_of_filing || "—"}
          </span>
        </div>

        <div>
          <span className="text-slate-400 block text-[11px]">IPO Location</span>
          <span className="text-slate-700 block">
            {patent.ipo_location || "—"}
          </span>
        </div>
      </div>

      {(patent.no_of_claims !== null || patent.no_of_pages !== null) && (
        <div className="flex items-center gap-4 mt-2 pt-2 border-t border-slate-50 text-[11px] text-slate-400">
          {patent.no_of_claims !== null && patent.no_of_claims !== undefined && (
            <span>Claims: <strong className="text-slate-600 font-medium">{patent.no_of_claims}</strong></span>
          )}
          {patent.no_of_pages !== null && patent.no_of_pages !== undefined && (
            <span>Pages: <strong className="text-slate-600 font-medium">{patent.no_of_pages}</strong></span>
          )}
          <span className="ml-auto text-slate-300 font-mono text-[10px]">
            ID: {patent.id}
          </span>
        </div>
      )}
    </div>
  );
}
