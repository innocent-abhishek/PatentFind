import React, { createContext, useContext, useState, useEffect } from "react";
import { loginUser as apiLogin, registerUser as apiRegister } from "../api";

const AuthContext = createContext(null);

const TOKEN_KEY = "patentfind_access_token";
const USER_KEY = "patentfind_auth_user";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [isInitializing, setIsInitializing] = useState(true);

  // Initialize auth state from localStorage on application load
  useEffect(() => {
    try {
      const storedToken = localStorage.getItem(TOKEN_KEY);
      const storedUser = localStorage.getItem(USER_KEY);
      if (storedToken && storedUser) {
        setToken(storedToken);
        setUser(JSON.parse(storedUser));
      }
    } catch (err) {
      console.warn("Failed to restore auth session from localStorage:", err);
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
    } finally {
      setIsInitializing(false);
    }
  }, []);

  /**
   * Authenticate with username/email and password.
   * Stores the JWT token in localStorage and updates current auth state.
   */
  const login = async (username, password) => {
    const data = await apiLogin(username, password);
    if (data && data.access_token && data.user) {
      setToken(data.access_token);
      setUser(data.user);
      localStorage.setItem(TOKEN_KEY, data.access_token);
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
    }
    return data;
  };

  /**
   * Public user registration. Never sets admin role.
   */
  const register = async (username, email, password) => {
    return await apiRegister(username, email, password);
  };

  /**
   * Clear local session.
   * Note: As a student project using client-side JWT storage, deleting the local
   * token stops the client from sending it. A full server-side revocation would require
   * a token blacklist on the backend.
   */
  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  };

  const value = {
    user,
    token,
    isAuthenticated: Boolean(token && user),
    isAdmin: user?.role === "admin",
    isInitializing,
    login,
    register,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
