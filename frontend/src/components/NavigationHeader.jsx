import React from "react";
import { useAuth } from "../context/AuthContext";

export default function NavigationHeader({ currentView, onViewChange }) {
  const { user, isAuthenticated, isAdmin, logout } = useAuth();

  return (
    <header className="bg-white border-b border-slate-200/80 sticky top-0 z-30 shadow-xs">
      <div className="max-w-6xl mx-auto px-4 py-3.5 sm:px-6 flex items-center justify-between">
        {/* Brand Mark and Title */}
        <div
          onClick={() => onViewChange("dashboard")}
          className="flex items-center gap-3 cursor-pointer select-none"
        >
          <div className="w-10 h-10 rounded-lg bg-slate-900 text-white flex items-center justify-center font-bold text-lg shadow-xs">
            PF
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold tracking-tight text-slate-900 leading-tight">
                PatentFind
              </h1>
              <span className="hidden sm:inline-block px-2 py-0.5 rounded text-[11px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                IPO 2016-2023
              </span>
            </div>
            <p className="text-xs text-slate-500 font-medium">
              Discover. Search. Innovate.
            </p>
          </div>
        </div>

        {/* Navigation & Account Controls */}
        <div className="flex items-center gap-3 text-xs sm:text-sm">
          {/* Dashboard Tab */}
          <button
            type="button"
            onClick={() => onViewChange("dashboard")}
            className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
              currentView === "dashboard"
                ? "bg-slate-100 text-slate-900 font-semibold"
                : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
            }`}
          >
            Search Dashboard
          </button>

          {/* Admin CSV Import Tab (Admin Only) */}
          {isAdmin && (
            <button
              type="button"
              onClick={() => onViewChange("admin-import")}
              className={`px-3 py-1.5 rounded-lg font-medium transition-colors cursor-pointer ${
                currentView === "admin-import"
                  ? "bg-slate-100 text-slate-900 font-semibold"
                  : "text-slate-600 hover:text-slate-900 hover:bg-slate-50"
              }`}
            >
              CSV Import
            </button>
          )}

          <div className="h-4 w-px bg-slate-200 hidden sm:block"></div>

          {isAuthenticated ? (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="font-medium text-slate-800">
                  {user?.username}
                </span>
                {isAdmin ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-900 text-white uppercase tracking-wider">
                    Admin
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200">
                    Researcher
                  </span>
                )}
              </div>

              <button
                type="button"
                onClick={logout}
                className="px-3 py-1.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-100 font-medium transition-colors cursor-pointer text-xs"
              >
                Sign Out
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onViewChange("login")}
                className={`px-3.5 py-1.5 rounded-lg font-medium transition-colors cursor-pointer text-xs ${
                  currentView === "login"
                    ? "bg-slate-900 text-white font-semibold"
                    : "border border-slate-300 text-slate-700 hover:bg-slate-100"
                }`}
              >
                Sign In
              </button>

              <button
                type="button"
                onClick={() => onViewChange("register")}
                className={`px-3.5 py-1.5 rounded-lg font-medium transition-colors cursor-pointer text-xs ${
                  currentView === "register"
                    ? "bg-slate-900 text-white font-semibold"
                    : "bg-slate-900 text-white hover:bg-slate-800"
                }`}
              >
                Register
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
