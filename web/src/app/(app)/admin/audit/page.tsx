"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  ChevronDown,
  ChevronRight,
  Loader2,
  ShieldAlert,
  ScrollText,
  Wrench,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AuditStep {
  tool_name: string;
  input_summary: string;
  output_summary: string;
  duration_ms: number;
}

interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  agent_name: string;
  input_summary: string;
  tokens_in: number;
  tokens_out: number;
  duration_ms: number;
  status: "success" | "error";
  steps: AuditStep[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatNumber(n: number | undefined | null): string {
  if (n == null) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDuration(ms: number | undefined | null): string {
  if (ms == null) return "0ms";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatTimestamp(dateStr: string): string {
  try {
    return new Date(dateStr).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AdminAuditPage() {
  const router = useRouter();
  const { user, isAdmin, isLoading: authLoading } = useAuth();

  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, router]);

  const loadAudit = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getAuditLog();
      setEntries(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load audit log"
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user && isAdmin) loadAudit();
  }, [user, isAdmin, loadAudit]);

  function toggleExpanded(id: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  if (authLoading) return null;

  if (!isAdmin) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="text-center">
          <div className="mx-auto flex size-16 items-center justify-center rounded-full bg-destructive/10">
            <ShieldAlert className="size-8 text-destructive" />
          </div>
          <h2 className="mt-4 text-lg font-semibold text-foreground">
            Access Denied
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            You do not have admin privileges to view this page.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary">
              <ScrollText className="size-5 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">Audit Log</h1>
              <p className="text-sm text-muted-foreground">
                Detailed execution history for all agent invocations
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {loading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="size-6 animate-spin text-primary" />
            <span className="ml-2 text-sm text-muted-foreground">
              Loading audit log...
            </span>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {!loading && !error && entries.length === 0 && (
          <div className="py-20 text-center">
            <ScrollText className="mx-auto size-10 text-muted-foreground" />
            <p className="mt-3 text-sm text-muted-foreground">
              No audit entries found.
            </p>
          </div>
        )}

        {!loading && !error && entries.length > 0 && (
          <div className="rounded-xl bg-card ring-1 ring-foreground/10">
            <div className="px-4 py-3">
              <span className="text-sm font-medium text-muted-foreground">
                {entries.length} entr{entries.length !== 1 ? "ies" : "y"}
              </span>
            </div>
            <Separator />
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[32px]" />
                  <TableHead>Timestamp</TableHead>
                  <TableHead>User</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead className="max-w-[200px]">Input</TableHead>
                  <TableHead className="text-right">Tokens</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {entries.map((entry) => {
                  const isExpanded = expandedIds.has(entry.id);
                  const hasSteps = entry.steps && entry.steps.length > 0;

                  return (
                    <TableRow
                      key={entry.id}
                      className="group"
                      aria-expanded={isExpanded}
                    >
                      <TableCell colSpan={8} className="p-0">
                        {/* Main row */}
                        <div
                          className={`flex items-center text-sm ${hasSteps ? "cursor-pointer" : ""}`}
                          onClick={() => hasSteps && toggleExpanded(entry.id)}
                          onKeyDown={(e) => {
                            if (hasSteps && e.key === "Enter")
                              toggleExpanded(entry.id);
                          }}
                          role={hasSteps ? "button" : undefined}
                          tabIndex={hasSteps ? 0 : undefined}
                        >
                          {/* Expand toggle */}
                          <div className="flex w-10 shrink-0 items-center justify-center py-2">
                            {hasSteps ? (
                              isExpanded ? (
                                <ChevronDown className="size-4 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="size-4 text-muted-foreground" />
                              )
                            ) : (
                              <span className="size-4" />
                            )}
                          </div>

                          {/* Timestamp */}
                          <div className="w-[140px] shrink-0 py-2 text-muted-foreground">
                            {formatTimestamp(entry.timestamp)}
                          </div>

                          {/* User */}
                          <div className="w-[160px] shrink-0 truncate py-2 font-medium text-foreground">
                            {entry.user_email}
                          </div>

                          {/* Agent */}
                          <div className="w-[140px] shrink-0 py-2 text-muted-foreground">
                            {entry.agent_name}
                          </div>

                          {/* Input */}
                          <div className="min-w-0 flex-1 truncate py-2 pr-3 text-muted-foreground">
                            {entry.input_summary}
                          </div>

                          {/* Tokens */}
                          <div className="w-[90px] shrink-0 py-2 text-right text-muted-foreground">
                            {formatNumber(entry.tokens_in + entry.tokens_out)}
                          </div>

                          {/* Duration */}
                          <div className="w-[80px] shrink-0 py-2 text-right text-muted-foreground">
                            {formatDuration(entry.duration_ms)}
                          </div>

                          {/* Status */}
                          <div className="w-[80px] shrink-0 py-2 pr-4">
                            {entry.status === "success" ? (
                              <Badge
                                variant="outline"
                                className="border-emerald-200 bg-emerald-50 text-emerald-700"
                              >
                                OK
                              </Badge>
                            ) : (
                              <Badge
                                variant="outline"
                                className="border-red-200 bg-red-50 text-red-700"
                              >
                                Error
                              </Badge>
                            )}
                          </div>
                        </div>

                        {/* Expanded steps */}
                        {isExpanded && hasSteps && (
                          <div className="border-t border-border bg-muted px-4 pb-3 pt-2">
                            <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                              <Wrench className="size-3" />
                              Execution Steps ({entry.steps.length})
                            </div>
                            <div className="space-y-1.5">
                              {entry.steps.map((step, idx) => (
                                <div
                                  key={idx}
                                  className="rounded-lg border border-border bg-card px-3 py-2"
                                >
                                  <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                      <span className="inline-flex size-5 items-center justify-center rounded bg-muted text-[10px] font-medium text-muted-foreground">
                                        {idx + 1}
                                      </span>
                                      <span className="text-sm font-medium text-muted-foreground">
                                        {step.tool_name}
                                      </span>
                                    </div>
                                    <span className="text-xs text-muted-foreground">
                                      {formatDuration(step.duration_ms)}
                                    </span>
                                  </div>
                                  <div className="mt-1.5 grid gap-1 pl-7 text-xs">
                                    <div>
                                      <span className="text-muted-foreground">
                                        Input:{" "}
                                      </span>
                                      <span className="text-muted-foreground">
                                        {step.input_summary}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="text-muted-foreground">
                                        Output:{" "}
                                      </span>
                                      <span className="text-muted-foreground">
                                        {step.output_summary}
                                      </span>
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}
