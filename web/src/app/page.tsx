"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { Landing } from "@/components/landing/landing";

export default function RootPage() {
  const router = useRouter();
  const { isAuthenticated, isLoading } = useAuth();

  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.replace("/home");
    }
  }, [isAuthenticated, isLoading, router]);

  // Resolving auth, or about to redirect an authenticated user.
  if (isLoading || isAuthenticated) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="size-8 animate-spin rounded-full border-2 border-muted border-t-primary" />
      </div>
    );
  }

  // Unauthenticated visitors get the marketing/architecture landing.
  return <Landing />;
}
