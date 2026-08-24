"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Database,
  FileSearch,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  flowPilotApi,
  threadIdForProposal,
  type FlowPilotAuditEvent,
  type FlowPilotEvidence,
  type FlowPilotExecution,
  type FlowPilotProposal,
  type FlowPilotRun,
  type FlowPilotTicket,
  type FlowPilotTicketSnapshot,
} from "@/lib/flowpilot-api";

function formatTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function formatDuration(value: number | null): string {
  if (value == null) return "—";
  return value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-48 overflow-auto rounded-lg bg-muted/60 p-3 text-xs leading-5 text-foreground/80">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function StatusBadge({ status }: { status: string }) {
  const tone = status === "RESOLVED" || status === "executed" || status === "approved"
    ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
    : status === "FAILED" || status === "ESCALATED" || status === "denied"
      ? "border-destructive/30 bg-destructive/10 text-destructive"
    : status === "WAITING_APPROVAL" || status === "RECONCILING" || status === "unknown" || status === "proposed"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300"
        : "border-border bg-muted text-muted-foreground";
  return <Badge variant="outline" className={tone}>{status}</Badge>;
}

export function FlowPilotWorkbench() {
  const [tickets, setTickets] = useState<FlowPilotTicket[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<FlowPilotTicketSnapshot | null>(null);
  const [loadingTickets, setLoadingTickets] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [decisionInFlight, setDecisionInFlight] = useState<string | null>(null);
  const [reconcileInFlight, setReconcileInFlight] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadTickets = useCallback(async () => {
    setLoadingTickets(true);
    try {
      const items = await flowPilotApi.listTickets();
      setTickets(items);
      setSelectedId((current) => current && items.some((item) => item.id === current) ? current : (items[0]?.id ?? null));
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "无法连接 FlowPilot API");
    } finally {
      setLoadingTickets(false);
    }
  }, []);

  const loadSnapshot = useCallback(async (ticketId: string) => {
    setLoadingDetail(true);
    try {
      setSnapshot(await flowPilotApi.getSnapshot(ticketId));
      setError(null);
    } catch (reason) {
      setSnapshot(null);
      setError(reason instanceof Error ? reason.message : "无法读取工单详情");
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => { void loadTickets(); }, [loadTickets]);
  useEffect(() => { if (selectedId) void loadSnapshot(selectedId); else setSnapshot(null); }, [selectedId, loadSnapshot]);

  const waitingApproval = useMemo(
    () => snapshot?.proposals.filter((item) => item.status === "proposed").length ?? 0,
    [snapshot],
  );

  async function decide(proposal: FlowPilotProposal, decision: "approved" | "denied") {
    if (!snapshot) return;
    const threadId = threadIdForProposal(snapshot.runs, proposal.id);
    if (!threadId) {
      setError("该历史运行摘要没有 thread_id，无法安全恢复审批 checkpoint；请重新启动该工单工作流。");
      return;
    }
    setDecisionInFlight(proposal.id);
    try {
      await flowPilotApi.decideWorkflowApproval(proposal.id, threadId, decision);
      await Promise.all([loadTickets(), loadSnapshot(snapshot.ticket.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "审批恢复失败");
    } finally {
      setDecisionInFlight(null);
    }
  }

  async function reconcile(execution: FlowPilotExecution) {
    if (!snapshot) return;
    setReconcileInFlight(execution.id);
    try {
      await flowPilotApi.reconcileExecution(execution.id);
      await Promise.all([loadTickets(), loadSnapshot(snapshot.ticket.id)]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "立即对账失败");
    } finally {
      setReconcileInFlight(null);
    }
  }

  return (
    <main className="min-h-screen bg-muted/30 text-foreground">
      <header className="border-b bg-background">
        <div className="mx-auto flex max-w-7xl items-start justify-between gap-5 px-5 py-6 lg:px-8">
          <div>
            <div className="flex items-center gap-2 text-sm font-medium text-primary"><Activity className="size-4" /> FlowPilot / Operations</div>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight">企业工单处置工作台</h1>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">真实读取工单、Evidence、Agent Run、结构化提案与审计；不展示 Prompt 或模型推理正文。</p>
          </div>
          <Button variant="outline" onClick={() => void loadTickets()} disabled={loadingTickets}>
            {loadingTickets ? <Loader2 className="animate-spin" /> : <RefreshCw />}
            刷新工单
          </Button>
        </div>
      </header>

      <div className="mx-auto max-w-7xl px-5 py-6 lg:px-8">
        <div className="mb-5 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-800 dark:text-amber-200">
          <ShieldCheck className="size-4 shrink-0" />
          本页是本机 Demo 工作台，使用受限本地 admin Header 访问 API；生产环境须切换 `jwt-local` 或联邦身份，不能把该 Header 模式当认证方案。
        </div>
        {error && <div className="mb-5 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive"><AlertTriangle className="mt-0.5 size-4 shrink-0" />{error}</div>}

        <div className="grid gap-6 lg:grid-cols-[300px_minmax(0,1fr)]">
          <aside>
            <Card>
              <CardHeader className="border-b"><CardTitle>工单队列</CardTitle><CardDescription>{tickets.length} 条可读取工单</CardDescription></CardHeader>
              <CardContent className="p-0">
                {loadingTickets && <div className="flex justify-center p-8"><Loader2 className="size-5 animate-spin text-muted-foreground" /></div>}
                {!loadingTickets && tickets.length === 0 && <Empty text="暂无工单。先通过 FlowPilot API 或 Mock Demo 创建一条工单。" />}
                <div className="divide-y">
                  {tickets.map((ticket) => <button key={ticket.id} type="button" onClick={() => setSelectedId(ticket.id)} className={`w-full px-4 py-3 text-left transition-colors hover:bg-muted/60 ${selectedId === ticket.id ? "bg-primary/5" : ""}`}>
                    <div className="flex items-center justify-between gap-2"><p className="truncate text-sm font-medium">{ticket.title}</p><span className="text-xs text-muted-foreground">P{ticket.priority}</span></div>
                    <div className="mt-2 flex items-center justify-between gap-2"><StatusBadge status={ticket.status} /><ChevronRight className="size-4 text-muted-foreground" /></div>
                    <p className="mt-2 truncate text-xs text-muted-foreground">{ticket.id}</p>
                  </button>)}
                </div>
              </CardContent>
            </Card>
          </aside>

          <section className="min-w-0 space-y-5">
            {loadingDetail && <Card><CardContent className="flex justify-center py-16"><Loader2 className="size-6 animate-spin text-muted-foreground" /></CardContent></Card>}
            {!loadingDetail && !snapshot && <Card><CardContent className="py-16"><Empty text="从左侧选择一条工单查看处置链路。" /></CardContent></Card>}
            {snapshot && <>
              <TicketOverview ticket={snapshot.ticket} waitingApproval={waitingApproval} />
              <div className="grid gap-5 xl:grid-cols-2">
                <EvidencePanel evidence={snapshot.evidence} />
                <ProposalPanel proposals={snapshot.proposals} runs={snapshot.runs} busyId={decisionInFlight} onDecide={decide} />
                <ExecutionPanel executions={snapshot.executions} busyId={reconcileInFlight} onReconcile={reconcile} />
                <RunPanel runs={snapshot.runs} />
                <AuditPanel events={snapshot.audit} />
              </div>
            </>}
          </section>
        </div>
      </div>
    </main>
  );
}

function Empty({ text }: { text: string }) { return <p className="px-5 py-8 text-center text-sm text-muted-foreground">{text}</p>; }

function TicketOverview({ ticket, waitingApproval }: { ticket: FlowPilotTicket; waitingApproval: number }) {
  return <Card><CardHeader><div className="flex flex-wrap items-start justify-between gap-3"><div><CardTitle>{ticket.title}</CardTitle><CardDescription className="mt-1">{ticket.description || "未填写描述"}</CardDescription></div><div className="flex items-center gap-2"><StatusBadge status={ticket.status} /><Badge variant="outline">优先级 P{ticket.priority}</Badge></div></div></CardHeader><CardContent className="grid gap-3 border-t pt-4 text-sm sm:grid-cols-4"><Metric label="提交人" value={ticket.submitter || "—"} /><Metric label="版本" value={String(ticket.version)} /><Metric label="待审批提案" value={String(waitingApproval)} /><Metric label="最近更新" value={formatTime(ticket.updated_at)} /></CardContent></Card>;
}

function Metric({ label, value }: { label: string; value: string }) { return <div><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 truncate font-medium">{value}</p></div>; }

function EvidencePanel({ evidence }: { evidence: FlowPilotEvidence[] }) {
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><FileSearch className="size-4 text-primary" /> Evidence</CardTitle><CardDescription>调查工具读取到的可追溯事实</CardDescription></CardHeader><CardContent className="space-y-3">{evidence.length === 0 ? <Empty text="该工单尚无 Evidence。" /> : evidence.map((item) => <details key={item.id} className="rounded-lg border p-3"><summary className="cursor-pointer list-none"><div className="flex items-center justify-between gap-3"><div><p className="font-medium">{item.tool}</p><p className="mt-1 text-xs text-muted-foreground">{item.source} · {formatTime(item.collected_at)}</p></div><ChevronRight className="size-4 text-muted-foreground" /></div></summary><div className="mt-3"><JsonBlock value={item.data} /></div></details>)}</CardContent></Card>;
}

function ProposalPanel({ proposals, runs, busyId, onDecide }: { proposals: FlowPilotProposal[]; runs: FlowPilotRun[]; busyId: string | null; onDecide: (proposal: FlowPilotProposal, decision: "approved" | "denied") => Promise<void>; }) {
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-primary" /> Action Proposals</CardTitle><CardDescription>模型建议只进入受控合同，执行仍需审批、状态机与幂等校验</CardDescription></CardHeader><CardContent className="space-y-3">{proposals.length === 0 ? <Empty text="该工单尚无提案。" /> : proposals.map((proposal) => { const threadId = threadIdForProposal(runs, proposal.id); const canDecide = proposal.status === "proposed" && !!threadId; const busy = busyId === proposal.id; return <div key={proposal.id} className="rounded-lg border p-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-sm font-medium">{proposal.action}</p><p className="mt-1 text-xs text-muted-foreground">{proposal.created_by} · {formatTime(proposal.created_at)}</p></div><div className="flex gap-2"><StatusBadge status={proposal.status} /><Badge variant="outline" className={proposal.risk === "high" ? "border-amber-500/30 text-amber-700 dark:text-amber-300" : ""}>{proposal.risk} risk</Badge></div></div><div className="mt-3"><JsonBlock value={proposal.params} /></div>{proposal.status === "proposed" && <div className="mt-3">{canDecide ? <div className="flex gap-2"><Button size="sm" disabled={busy} onClick={() => void onDecide(proposal, "approved")}>{busy ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}批准并恢复</Button><Button size="sm" variant="destructive" disabled={busy} onClick={() => void onDecide(proposal, "denied")}><XCircle />拒绝并升级</Button></div> : <p className="text-xs text-amber-700 dark:text-amber-300">历史 Agent Run 未记录 thread_id；为避免恢复错误 checkpoint，已禁用审批操作。</p>}</div>}</div>; })}</CardContent></Card>;
}

function ExecutionPanel({ executions, busyId, onReconcile }: { executions: FlowPilotExecution[]; busyId: string | null; onReconcile: (execution: FlowPilotExecution) => Promise<void>; }) {
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><RefreshCw className="size-4 text-primary" /> Executions</CardTitle><CardDescription>未知结果会先进入 RECONCILING，沿用原幂等键查询 SW 回执，不盲目新建副作用。</CardDescription></CardHeader><CardContent className="space-y-3">{executions.length === 0 ? <Empty text="该工单尚无执行记录。" /> : executions.map((item) => <div key={item.id} className="rounded-lg border p-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-mono text-sm font-medium">{item.id}</p><p className="mt-1 text-xs text-muted-foreground">业务执行 {item.attempts} 次 · 对账 {item.reconcile_attempts} 次</p></div><StatusBadge status={item.status} /></div><div className="mt-3 grid gap-2 text-xs sm:grid-cols-3"><Metric label="下次对账" value={formatTime(item.next_reconcile_at)} /><Metric label="最近对账" value={formatTime(item.last_reconciled_at)} /><Metric label="完成时间" value={formatTime(item.finished_at)} /></div>{item.result && <details className="mt-3"><summary className="cursor-pointer text-xs text-primary">查看安全结果/回执摘要</summary><div className="mt-2"><JsonBlock value={item.result} /></div></details>}{(item.status === "unknown" || item.status === "running") && <Button className="mt-3" size="sm" variant="outline" disabled={busyId === item.id} onClick={() => void onReconcile(item)}>{busyId === item.id ? <Loader2 className="animate-spin" /> : <RefreshCw />}立即对账</Button>}</div>)}</CardContent></Card>;
}

function RunPanel({ runs }: { runs: FlowPilotRun[] }) {
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4 text-primary" /> Agent Runs</CardTitle><CardDescription>运行摘要、模型用量与 TraceId；不持久化 Prompt/推理链</CardDescription></CardHeader><CardContent className="space-y-3">{runs.length === 0 ? <Empty text="该工单尚无 Agent Run。" /> : runs.map((run) => <div key={run.id} className="rounded-lg border p-3"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="font-medium">{run.agent}</p><p className="mt-1 text-xs text-muted-foreground">{run.model || "deterministic"} · {formatTime(run.created_at)}</p></div><span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock3 className="size-3" />{formatDuration(run.latency_ms)}</span></div><div className="mt-3 grid gap-2 text-xs sm:grid-cols-3"><Metric label="TraceId" value={run.trace_id || "—"} /><Metric label="Tokens" value={run.tokens?.total_tokens?.toString() || "未采集"} /><Metric label="Thread" value={typeof run.output.thread_id === "string" ? run.output.thread_id : "历史记录缺失"} /></div><details className="mt-3"><summary className="cursor-pointer text-xs text-primary">查看安全运行摘要</summary><div className="mt-2"><JsonBlock value={run.output} /></div></details></div>)}</CardContent></Card>;
}

function AuditPanel({ events }: { events: FlowPilotAuditEvent[] }) {
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><Database className="size-4 text-primary" /> Audit Trail</CardTitle><CardDescription>业务写入与操作者身份的持久化审计</CardDescription></CardHeader><CardContent className="space-y-0">{events.length === 0 ? <Empty text="该工单暂无审计事件。" /> : events.map((event) => <div key={event.id} className="flex gap-3 border-b py-3 last:border-b-0"><div className="mt-0.5 rounded-full bg-primary/10 p-1.5"><CheckCircle2 className="size-3.5 text-primary" /></div><div className="min-w-0 flex-1"><p className="font-mono text-xs font-medium">{event.action}</p><p className="mt-1 text-xs text-muted-foreground">{event.actor} ({event.actor_role}) · {formatTime(event.created_at)}</p><details className="mt-2"><summary className="cursor-pointer text-xs text-primary">查看前后快照</summary><div className="mt-2 grid gap-2 sm:grid-cols-2"><JsonBlock value={event.before} /><JsonBlock value={event.after} /></div></details></div></div>)}</CardContent></Card>;
}
