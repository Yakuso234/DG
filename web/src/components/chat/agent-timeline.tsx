"use client";

import { useState } from "react";
import { ChevronRight, Check, X } from "lucide-react";
import type { AgentStep } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Collapsible "agent activity" timeline — renders the tool-call steps streamed
 * over `event: step` SSE frames (orchestrator → specialist → tool).
 */
export function AgentTimeline({ steps }: { steps: AgentStep[] }) {
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;

  return (
    <div className="mt-2 max-w-md rounded-lg border bg-card/60 text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        <span>
          Agent activity · {steps.length} step{steps.length > 1 ? "s" : ""}
        </span>
      </button>
      {open && (
        <ol className="space-y-1.5 border-t px-2.5 py-2">
          {steps.map((s, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="rounded bg-primary/10 px-1.5 py-0.5 font-medium text-primary">
                {s.agent ?? "orchestrator"}
              </span>
              <span className="truncate font-mono text-foreground/80">{s.tool_name}</span>
              {s.status === "error" ? (
                <X className="size-3 shrink-0 text-destructive" />
              ) : (
                <Check className="size-3 shrink-0 text-emerald-500" />
              )}
              {typeof s.duration_ms === "number" && (
                <span className="ml-auto shrink-0 text-muted-foreground">{s.duration_ms}ms</span>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
