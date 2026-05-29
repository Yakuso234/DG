"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth-context";
import { visibleGroups, type NavItem } from "@/lib/nav";
import { cn } from "@/lib/utils";

const OPEN_EVENT = "ecommerce:open-command-palette";

/** Open the command palette from anywhere (e.g. the top-bar search button). */
export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

/**
 * Cmd/Ctrl-K command palette for quick navigation. Mounted once in the app
 * layout; opens on the shortcut or via {@link openCommandPalette}.
 */
export function CommandPalette() {
  const router = useRouter();
  const { isAdmin, user } = useAuth();
  const isSeller = user?.role === "seller" || isAdmin;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const items = useMemo<NavItem[]>(
    () => visibleGroups({ isAdmin, isSeller }).flatMap((g) => g.items),
    [isAdmin, isSeller],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? items.filter((i) => i.label.toLowerCase().includes(q)) : items;
  }, [items, query]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    }
    function onOpen() {
      setOpen(true);
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_EVENT, onOpen);
    };
  }, []);

  function handleOpenChange(next: boolean) {
    setOpen(next);
    if (next) {
      setQuery("");
      setActive(0);
    }
  }

  const go = useCallback(
    (href: string) => {
      setOpen(false);
      router.push(href);
    },
    [router],
  );

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = filtered[active];
      if (item) go(item.href);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="overflow-hidden p-0 sm:max-w-lg"
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <div className="flex items-center gap-2 border-b px-3">
          <Search className="size-4 shrink-0 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onInputKey}
            placeholder="Search pages…"
            aria-label="Search pages"
            className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden rounded border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
            esc
          </kbd>
        </div>
        <ul className="max-h-72 overflow-y-auto p-2">
          {filtered.length === 0 && (
            <li className="px-3 py-6 text-center text-sm text-muted-foreground">
              No results
            </li>
          )}
          {filtered.map((item, i) => {
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <button
                  type="button"
                  onClick={() => go(item.href)}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                    i === active
                      ? "bg-accent text-accent-foreground"
                      : "text-foreground",
                  )}
                >
                  <Icon className="size-4 text-muted-foreground" />
                  <span className="flex-1">{item.label}</span>
                  {i === active && (
                    <CornerDownLeft className="size-3.5 text-muted-foreground" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>
      </DialogContent>
    </Dialog>
  );
}
