import React, { useState, useRef } from "react";
import { uploadPatentCsv } from "../api";

export default function CsvUploadSection({ token, onUploadSuccess }) {
  const [file, setFile] = useState(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const [uploadResult, setUploadResult] = useState(null);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (selected) {
      if (!selected.name.toLowerCase().endsWith(".csv")) {
        setUploadError("Please select a file with .csv extension.");
        setFile(null);
        return;
      }
      setFile(selected);
      setUploadError(null);
      setUploadResult(null);
    }
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = (e) => {
    e.preventDefault();
    setIsDragging(false);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) {
      if (!dropped.name.toLowerCase().endsWith(".csv")) {
        setUploadError("Please drop a valid .csv file.");
        setFile(null);
        return;
      }
      setFile(dropped);
      setUploadError(null);
      setUploadResult(null);
    }
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file || isUploading) return;

    setIsUploading(true);
    setUploadError(null);
    setUploadResult(null);

    try {
      const result = await uploadPatentCsv(file, token);
      setUploadResult(result);
      if (result.imported_count > 0 && onUploadSuccess) {
        onUploadSuccess();
      }
    } catch (err) {
      setUploadError(err.message || "Failed to upload CSV file.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleReset = () => {
    setFile(null);
    setUploadError(null);
    setUploadResult(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const downloadSampleCsv = () => {
    const sampleContent =
      "APPLICATION_NUMBER,TITLE_OF_INVENTION,PUBLICATION_DATE,FIELD_OF_INVENTION,IPO_LOCATION,PUBLICATION_NUMBER,DATE_OF_FILING,NO_OF_PAGES,NO_OF_CLAIMS\n" +
      "SAMPLE/2023/001,SYSTEM AND METHOD FOR NEURAL NETWORK OPTIMIZATION,15/06/2023,COMPUTER SCIENCE,Delhi,24/2023,10/01/2023,24,12\n" +
      "SAMPLE/2023/002,BIOCOMPATIBLE POLYMER SCAFFOLD FOR TISSUE REGENERATION,20/08/2023,BIOMEDICAL,Mumbai,34/2023,12/02/2023,32,16\n";
    const blob = new Blob([sampleContent], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", "patentfind_sample_template.csv");
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <div className="bg-white border border-slate-200 rounded-xl p-5 sm:p-6 mb-8 shadow-xs">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 mb-4 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500"></span>
            <h3 className="text-base font-bold text-slate-900">
              Bulk Patent CSV Import
            </h3>
            <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-900 text-white tracking-wider uppercase">
              Admin
            </span>
          </div>
          <p className="text-xs text-slate-500 mt-0.5">
            Import patent records in bulk. Duplicates are skipped safely and search indexes synchronize automatically.
          </p>
        </div>

        <button
          type="button"
          onClick={downloadSampleCsv}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 text-xs font-medium cursor-pointer transition-colors"
        >
          <svg className="w-3.5 h-3.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Download Sample CSV
        </button>
      </div>

      {/* Upload Zone */}
      {!uploadResult && (
        <form onSubmit={handleUpload}>
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`border-2 border-dashed rounded-xl p-6 sm:p-8 text-center cursor-pointer transition-all ${
              isDragging
                ? "border-slate-900 bg-slate-50 scale-[0.99]"
                : file
                ? "border-emerald-400 bg-emerald-50/20"
                : "border-slate-300 hover:border-slate-400 bg-[#F9F8F6]/60"
            }`}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="hidden"
            />

            <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-700 flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>

            {file ? (
              <div>
                <p className="text-sm font-semibold text-slate-900">{file.name}</p>
                <p className="text-xs text-slate-500 mt-1">
                  {(file.size / 1024).toFixed(1)} KB &bull; Ready to upload
                </p>
                <span className="inline-block mt-2 text-[11px] text-slate-500 underline hover:text-slate-800">
                  Click or drop to replace file
                </span>
              </div>
            ) : (
              <div>
                <p className="text-sm font-semibold text-slate-800">
                  Drop your CSV file here, or <span className="text-slate-900 underline">browse</span>
                </p>
                <p className="text-xs text-slate-500 mt-1">
                  Supports up to 15 MB and 10,000 patent records per file.
                </p>
                <p className="text-[11px] text-slate-400 mt-2 font-mono">
                  Required columns: APPLICATION_NUMBER, TITLE_OF_INVENTION, PUBLICATION_DATE (DD/MM/YYYY)
                </p>
              </div>
            )}
          </div>

          {/* Error Message */}
          {uploadError && (
            <div className="mt-4 bg-rose-50 border border-rose-200 rounded-lg p-3 text-xs text-rose-800 flex items-start gap-2">
              <svg className="w-4 h-4 text-rose-600 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <p className="font-semibold">Upload Failed</p>
                <p className="mt-0.5">{uploadError}</p>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="mt-4 flex items-center justify-end gap-2.5">
            {file && (
              <button
                type="button"
                onClick={handleReset}
                disabled={isUploading}
                className="px-3.5 py-1.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 text-xs font-medium cursor-pointer transition-colors"
              >
                Clear
              </button>
            )}

            <button
              type="submit"
              disabled={!file || isUploading}
              className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold text-white transition-all ${
                !file || isUploading
                  ? "bg-slate-400 cursor-not-allowed"
                  : "bg-slate-900 hover:bg-slate-800 shadow-xs cursor-pointer"
              }`}
            >
              {isUploading ? (
                <>
                  <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"></path>
                  </svg>
                  <span>Processing & Indexing...</span>
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l4-4m0 0l4 4m-4-4v12" />
                  </svg>
                  <span>Upload & Import Records</span>
                </>
              )}
            </button>
          </div>
        </form>
      )}

      {/* Upload Results Summary Card */}
      {uploadResult && (
        <div className="space-y-4">
          <div className="bg-slate-50 border border-slate-200 rounded-xl p-4">
            <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-200">
              <div className="flex items-center gap-2">
                <span className={`w-3 h-3 rounded-full ${uploadResult.imported_count > 0 ? "bg-emerald-500" : "bg-amber-500"}`}></span>
                <h4 className="text-sm font-bold text-slate-900">Import Summary</h4>
              </div>
              <button
                type="button"
                onClick={handleReset}
                className="text-xs text-slate-600 hover:text-slate-900 font-medium underline cursor-pointer"
              >
                Upload Another File
              </button>
            </div>

            <p className="text-xs text-slate-700 mb-4">{uploadResult.message}</p>

            {/* Metrics Badges */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              <div className="bg-white border border-slate-200 rounded-lg p-2.5 text-center shadow-2xs">
                <span className="text-[10px] uppercase font-semibold text-slate-500 tracking-wider">Total Rows</span>
                <p className="text-lg font-bold text-slate-900">{uploadResult.total_rows.toLocaleString()}</p>
              </div>

              <div className="bg-emerald-50/50 border border-emerald-200 rounded-lg p-2.5 text-center shadow-2xs">
                <span className="text-[10px] uppercase font-semibold text-emerald-700 tracking-wider">Imported</span>
                <p className="text-lg font-bold text-emerald-800">{uploadResult.imported_count.toLocaleString()}</p>
              </div>

              <div className="bg-amber-50/50 border border-amber-200 rounded-lg p-2.5 text-center shadow-2xs">
                <span className="text-[10px] uppercase font-semibold text-amber-700 tracking-wider">Skipped Duplicates</span>
                <p className="text-lg font-bold text-amber-800">{uploadResult.duplicate_count.toLocaleString()}</p>
              </div>

              <div className="bg-rose-50/50 border border-rose-200 rounded-lg p-2.5 text-center shadow-2xs">
                <span className="text-[10px] uppercase font-semibold text-rose-700 tracking-wider">Failed Errors</span>
                <p className="text-lg font-bold text-rose-800">{uploadResult.failed_count.toLocaleString()}</p>
              </div>
            </div>
          </div>

          {/* Skipped Duplicates Table */}
          {uploadResult.skipped_duplicates && uploadResult.skipped_duplicates.length > 0 && (
            <div className="bg-white border border-amber-200 rounded-xl p-4 shadow-xs">
              <h5 className="text-xs font-bold text-amber-900 flex items-center gap-1.5 mb-2.5">
                <svg className="w-4 h-4 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
                Duplicate Rows Skipped ({uploadResult.skipped_duplicates.length})
              </h5>
              <div className="max-h-48 overflow-y-auto border border-amber-100 rounded-lg text-xs">
                <table className="min-w-full divide-y divide-amber-100">
                  <thead className="bg-amber-50 text-slate-700 sticky top-0 font-semibold">
                    <tr>
                      <th className="px-3 py-1.5 text-left text-[11px]">Row</th>
                      <th className="px-3 py-1.5 text-left text-[11px]">Application Number</th>
                      <th className="px-3 py-1.5 text-left text-[11px]">Reason</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-amber-50 font-mono text-[11px] bg-white">
                    {uploadResult.skipped_duplicates.map((dup, i) => (
                      <tr key={i} className="hover:bg-amber-50/40">
                        <td className="px-3 py-1 text-slate-500 font-bold">#{dup.row}</td>
                        <td className="px-3 py-1 text-slate-900 font-semibold">{dup.application_number}</td>
                        <td className="px-3 py-1 text-amber-800 font-sans">{dup.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Validation Errors Table */}
          {uploadResult.validation_errors && uploadResult.validation_errors.length > 0 && (
            <div className="bg-white border border-rose-200 rounded-xl p-4 shadow-xs">
              <h5 className="text-xs font-bold text-rose-900 flex items-center gap-1.5 mb-2.5">
                <svg className="w-4 h-4 text-rose-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Validation Errors ({uploadResult.validation_errors.length})
              </h5>
              <div className="max-h-48 overflow-y-auto border border-rose-100 rounded-lg text-xs">
                <table className="min-w-full divide-y divide-rose-100">
                  <thead className="bg-rose-50 text-slate-700 sticky top-0 font-semibold">
                    <tr>
                      <th className="px-3 py-1.5 text-left text-[11px]">Row</th>
                      <th className="px-3 py-1.5 text-left text-[11px]">Field</th>
                      <th className="px-3 py-1.5 text-left text-[11px]">Error Description</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-rose-50 font-mono text-[11px] bg-white">
                    {uploadResult.validation_errors.map((err, i) => (
                      <tr key={i} className="hover:bg-rose-50/40">
                        <td className="px-3 py-1 text-slate-500 font-bold">#{err.row}</td>
                        <td className="px-3 py-1 text-rose-700 font-semibold">{err.field}</td>
                        <td className="px-3 py-1 text-slate-700 font-sans">{err.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
