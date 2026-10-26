"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, tokenStore, type User } from "@/lib/api";

type AuthState = {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthState | null>(null);

const PUBLIC_PATHS = ["/login", "/signup"];

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  // On first load, check any saved token with the backend
  useEffect(() => {
    async function restore() {
      if (tokenStore.get()) {
        try {
          setUser(await api.me());
        } catch {
          tokenStore.clear();
        }
      }
      setReady(true);
    }
    restore();
  }, []);

  const isPublic = PUBLIC_PATHS.includes(pathname);

  // Keep logged-out visitors on the login/signup pages, and logged-in users off them
  useEffect(() => {
    if (!ready) return;
    if (!user && !isPublic) router.replace("/login");
    if (user && isPublic) router.replace("/");
  }, [ready, user, isPublic, router]);

  async function finishAuth(token: string) {
    tokenStore.set(token);
    setUser(await api.me());
  }

  const value: AuthState = {
    user,
    login: async (email, password) => finishAuth((await api.login(email, password)).access_token),
    signup: async (email, password) => finishAuth((await api.signup(email, password)).access_token),
    logout: () => {
      tokenStore.clear();
      setUser(null);
    },
  };

  // Don't flash protected content (or the login form) while redirecting.
  // Public pages render immediately so they are part of the server render.
  if (isPublic ? !!user : !ready || !user) return null;

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
