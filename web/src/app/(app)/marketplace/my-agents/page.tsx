"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
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
  Search,
  Package,
  Tag,
  BarChart3,
  Truck,
  Headphones,
  Loader2,
  KeyRound,
  Store,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Agent icon map
// ---------------------------------------------------------------------------

const AGENT_ICONS: Record<string, React.ElementType> = {
  product_discovery: Search,
  order_management: Package,
  pricing_promotions: Tag,
  review_sentiment: BarChart3,
  inventory_fulfillment: Truck,
  customer_support: Headphones,
};

function getAgentIcon(agentName: string | undefined): React.ElementType {
  if (!agentName) return Store;
  for (const [key, Icon] of Object.entries(AGENT_ICONS)) {
    if (agentName.includes(key)) return Icon;
  }
  return Store;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface MyAgent {
  agent_name: string;
  display_name: string;
  role: string;
  granted_at: string;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MyAgentsPage() {
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();

  const [agents, setAgents] = useState<MyAgent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      router.replace("/login");
    }
  }, [user, authLoading, router]);

  const loadMyAgents = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getMyAgents();
      setAgents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user) loadMyAgents();
  }, [user, loadMyAgents]);

  function formatDate(dateStr: string): string {
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch {
      return dateStr;
    }
  }

  if (authLoading || !user) return null;

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="flex size-10 items-center justify-center rounded-lg bg-primary">
              <KeyRound className="size-5 text-primary-foreground" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-foreground">My Agents</h1>
              <p className="text-sm text-muted-foreground">
                Agents you have been granted access to
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="mx-auto max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
        {loading && (
          <div className="flex items-center justify-center py-20">
            <Loader2 className="size-6 animate-spin text-primary" />
            <span className="ml-2 text-sm text-muted-foreground">
              Loading your agents...
            </span>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {!loading && !error && agents.length === 0 && (
          <div className="py-20 text-center">
            <KeyRound className="mx-auto size-10 text-muted-foreground" />
            <p className="mt-3 text-sm font-medium text-foreground">
              No agents yet
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Visit the marketplace to request access to available agents.
            </p>
          </div>
        )}

        {!loading && !error && agents.length > 0 && (
          <div className="rounded-xl border border-border bg-card">
            <div className="px-4 py-3">
              <span className="text-sm font-medium text-foreground">
                {agents.length} agent{agents.length !== 1 ? "s" : ""} available
              </span>
            </div>
            <Separator />
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="w-[40%]">Agent</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Granted</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.map((agent) => {
                  const IconComponent = getAgentIcon(agent.agent_name);
                  return (
                    <TableRow key={agent.agent_name}>
                      <TableCell>
                        <div className="flex items-center gap-3">
                          <div className="flex size-8 items-center justify-center rounded-md bg-primary/10">
                            <IconComponent className="size-4 text-primary" />
                          </div>
                          <span className="font-medium text-foreground">
                            {agent.display_name}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge
                          variant="secondary"
                          className="font-normal text-xs"
                        >
                          {agent.role}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDate(agent.granted_at)}
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
