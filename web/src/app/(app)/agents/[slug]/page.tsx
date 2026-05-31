import { AGENTS } from "@/lib/agents";
import { AgentDetailClient } from "./agent-detail-client";

export function generateStaticParams() {
  return AGENTS.map((a) => ({ slug: a.slug }));
}

export default function AgentDetailPage({
  params,
}: {
  params: { slug: string };
}) {
  return <AgentDetailClient slug={params.slug} />;
}
