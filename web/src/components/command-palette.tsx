"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, CornerDownLeft, PlayCircle } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useAuth } from "@/lib/auth-context";
import { visibleGroups, type NavItem } from "@/lib/nav";
import { DEMO_SCENARIOS, chatPromptHref } from "@/lib/scenarios";
import { cn } from "@/lib/utils";

const OPEN_EVENT = "ecommerce:open-command-palette";

/** Open the command palette from anywhere (e.g. the top-bar search button). */
export function openCommandPalette() {
  window.dispatchEvent(new CustomEvent(OPEN_EVENT));
}

/** Unified item for keyboard navigation — either a nav page or a demo scenario. */
type PaletteItem =
  | { kind: "nav"; nav: NavItem }
  | { kind: "scenario"; label: string; description: string; href: string };

/**
 * Cmd/Ctrl-K command palette for quick navigation and demo scenario launching.
 * Mounted once in the app layout.
 */
export function CommandPalette() {
  const router = useRouter();
  const { isAdmin, user } = useAuth();
  const isSeller = user?.role === "seller" || isAdmin;

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const navItems = useMemo<NavItem[]>(
    () => visibleGroups({ isAdmin, isSeller }).flatMap((g) => g.items),
    [isAdmin, isSeller],
  );

  const allItems = useMemo<PaletteItem[]>(() => {
    const navPaletteItems: PaletteItem[] = navItems.map((nav) => ({
      kind: "nav",
      nav,
    }));
    const scenarioPaletteItems: PaletteItem[] = DEMO_SCENARIOS.map((s) => ({
      kind: "scenario",
      label: s.label,
      description: s.description,
      href: chatPromptHref(s.prompt),
    }));
    return [...navPaletteItems, ...scenarioPaletteItems];
  }, [navItems]);

  const filtered = useMemo<PaletteItem[]>(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allItems;
    return allItems.filter((item) => {
      const text =
        item.kind === "nav"
          ? item.nav.label
          : `${item.label} ${item.description}`;
      return text.toLowerCase().includes(q);
    });
  }, [allItems, query]);

  // Split filtered list back into nav + scenario groups for rendering
  const filteredNav = filtered.filter((i): i is Extract<PaletteItem, { kind: "nav" }> => i.kind === "nav");
  const filteredScenarios = filtered.filter((i): i is Extract<PaletteItem, { kind: "scenario" }> => i.kind === "scenario");

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
      if (!item) return;
      go(item.kind === "nav" ? item.nav.href : item.href);
    }
  }

  const isEmpty = filtered.length === 0;
  // Global index offset so keyboard active state spans both sections
  const navOffset = 0;
  const scenarioOffset = filteredNav.length;

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
            placeholder="Search pages or demo scenarios…"
            aria-label="Search pages or demo scenarios"
            className="h-11 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
          />
          <kbd className="hidden rounded border bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
            esc
          </kbd>
        </div>

        <div className="max-h-[26rem] overflow-y-auto">
          {isEmpty && (
            <p className="px-3 py-6 text-center text-sm text-muted-foreground">
              No results
            </p>
          )}

          {/* Nav pages */}
          {filteredNav.length > 0 && (
            <section>
              <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Pages
              </p>
              <ul className="px-2 pb-1">
                {filteredNav.map((item, i) => {
                  const Icon = item.nav.icon;
                  const globalIdx = navOffset + i;
                  return (
                    <li key={item.nav.href}>
                      <button
                        type="button"
                        onClick={() => go(item.nav.href)}
                        onMouseEnter={() => setActive(globalIdx)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                          globalIdx === active
                            ? "bg-accent text-accent-foreground"
                            : "text-foreground",
                        )}
                      >
                        <Icon className="size-4 text-muted-foreground" />
                        <span className="flex-1">{item.nav.label}</span>
                        {globalIdx === active && (
                          <CornerDownLeft className="size-3.5 text-muted-foreground" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}

          {/* Demo scenarios */}
          {filteredScenarios.length > 0 && (
            <section>
              <p className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                Demo scenarios
              </p>
              <ul className="px-2 pb-2">
                {filteredScenarios.map((item, i) => {
                  const globalIdx = scenarioOffset + i;
                  return (
                    <li key={item.href}>
                      <button
                        type="button"
                        onClick={() => go(item.href)}
                        onMouseEnter={() => setActive(globalIdx)}
                        className={cn(
                          "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                          globalIdx === active
                            ? "bg-accent text-accent-foreground"
                            : "text-foreground",
                        )}
                      >
                        <PlayCircle className="size-4 shrink-0 text-primary" />
                        <span className="flex-1 font-medium">{item.label}</span>
                        <span className="hidden truncate text-xs text-muted-foreground sm:block sm:max-w-[180px]">
                          {item.description}
                        </span>
                        {globalIdx === active && (
                          <CornerDownLeft className="size-3.5 shrink-0 text-muted-foreground" />
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
