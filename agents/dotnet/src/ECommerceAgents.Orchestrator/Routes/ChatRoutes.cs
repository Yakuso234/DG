using Dapper;
using ECommerceAgents.Shared.Context;
using ECommerceAgents.Shared.Data;
using ECommerceAgents.Shared.Telemetry;
using Microsoft.Agents.AI;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.AI;
using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace ECommerceAgents.Orchestrator.Routes;

/// <summary>
/// Chat endpoints: a blocking <c>POST /api/chat</c> and an SSE
/// <c>POST /api/chat/stream</c>. Both delegate to the orchestrator
/// agent, which picks a specialist via the <c>call_specialist_agent</c>
/// tool. Mirrors Python's <c>orchestrator/routes.py</c> chat handlers:
/// anonymous (storefront) callers get a response with nothing persisted;
/// authenticated callers get their turn saved to <c>conversations</c>/
/// <c>messages</c>, with the last 50 messages loaded back as history and
/// the turn logged to <c>usage_logs</c>.
/// </summary>
public static class ChatRoutes
{
    public sealed record ChatRequest(string Message, string? ConversationId, List<HistoryEntry>? History);
    public sealed record ChatResponse(string Response, string ConversationId, List<string> AgentsInvolved);

    public static IEndpointRouteBuilder MapChatRoutes(this IEndpointRouteBuilder routes)
    {
        routes.MapPost("/api/chat", SendAsync);
        routes.MapPost("/api/chat/stream", StreamAsync);
        return routes;
    }

    private static async Task<IResult> SendAsync(
        [FromBody] ChatRequest request,
        AIAgent agent,
        DatabasePool pool,
        UsageRecorder usage
    )
    {
        if (string.IsNullOrWhiteSpace(request?.Message))
        {
            return Results.BadRequest(new { detail = "message is required" });
        }

        var (ctx, error) = await PrepareConversationAsync(pool, request.Message, request.ConversationId);
        if (error is not null)
        {
            return error;
        }

        using var scope = RequestContext.Scope(
            RequestContext.CurrentUserEmail,
            RequestContext.CurrentUserRole,
            RequestContext.CurrentSessionId,
            ctx!.History
        );

        // Python's blocking handler never actually grows agents_involved beyond
        // ["orchestrator"] either (routes.py:423-461) — no mutation between init
        // and return — so this stays static rather than wiring up the dynamic
        // capture used by the streaming endpoint below.
        var agentsInvolved = new List<string> { "orchestrator" };

        var sw = Stopwatch.StartNew();
        var response = await agent.RunAsync(BuildMessages(ctx.History));
        sw.Stop();

        await PersistAssistantMessageAsync(
            pool, usage, ctx, request.Message, response.Text, agentsInvolved, (int)sw.ElapsedMilliseconds
        );

        return Results.Ok(new ChatResponse(response.Text, ctx.ConversationId, agentsInvolved));
    }

    private static async Task StreamAsync(
        HttpContext context,
        AIAgent agent,
        DatabasePool pool,
        UsageRecorder usage
    )
    {
        var request = await context.Request.ReadFromJsonAsync<ChatRequest>();
        if (string.IsNullOrWhiteSpace(request?.Message))
        {
            context.Response.StatusCode = 400;
            await context.Response.WriteAsync("missing message");
            return;
        }

        var (ctx, error) = await PrepareConversationAsync(pool, request.Message, request.ConversationId);
        if (error is not null)
        {
            await error.ExecuteAsync(context);
            return;
        }

        context.Response.Headers.ContentType = "text/event-stream";
        context.Response.Headers.CacheControl = "no-cache";
        context.Response.Headers["X-Accel-Buffering"] = "no";

        using var scope = RequestContext.Scope(
            RequestContext.CurrentUserEmail,
            RequestContext.CurrentUserRole,
            RequestContext.CurrentSessionId,
            ctx!.History
        );

        var sw = Stopwatch.StartNew();
        var responseText = new StringBuilder();
        await foreach (var update in agent.RunStreamingAsync(BuildMessages(ctx.History)))
        {
            if (string.IsNullOrEmpty(update.Text))
            {
                continue;
            }

            responseText.Append(update.Text);
            // Matches Python's raw pass-through (agent_host.py: yield f"data: {chunk}\n\n") —
            // no newline escaping. The frontend's SSE parser (web/src/lib/api.ts::chatStream)
            // reconstructs multi-line data payloads using real newlines per the SSE spec;
            // escaping \n to the literal two-character "\n" here broke both the visible text
            // (literal backslash-n showing up in the UI) and the ```product/```order card
            // detection regex, which requires a real newline after the fence marker.
            var payload = $"data: {update.Text}\n\n";
            await context.Response.WriteAsync(payload, Encoding.UTF8);
            await context.Response.Body.FlushAsync();
        }
        sw.Stop();

        // Dynamic agents_involved — mirrors Python's current_steps capture
        // (routes.py:651-655). RequestContext.CurrentInvokedAgents is populated by
        // OrchestratorTools.CallSpecialistAgent for every A2A call made during this
        // request (RequestContext.Scope above gave this request a fresh list).
        var agentsInvolved = new List<string> { "orchestrator" };
        agentsInvolved.AddRange(
            RequestContext.CurrentInvokedAgents.Distinct().Where(a => a != "orchestrator")
        );

        var metadataPayload = JsonSerializer.Serialize(new
        {
            conversation_id = ctx.ConversationId,
            agents_involved = agentsInvolved,
        });
        await context.Response.WriteAsync($"event: metadata\ndata: {metadataPayload}\n\n", Encoding.UTF8);
        await context.Response.WriteAsync("event: done\ndata: [DONE]\n\n");
        await context.Response.Body.FlushAsync();

        await PersistAssistantMessageAsync(
            pool, usage, ctx, request.Message, responseText.ToString(), agentsInvolved, (int)sw.ElapsedMilliseconds,
            metadata: new Dictionary<string, object> { ["agents_involved"] = agentsInvolved }
        );
    }

    // ─────────────────────── shared persistence helpers ──────────────────────

    /// <summary>Resolved once per request: whether the caller is anonymous, the
    /// (possibly newly created) conversation id, their resolved user id, and the
    /// history to feed into <see cref="RequestContext.Scope"/>.</summary>
    private sealed record ConversationContext(bool IsAnon, string ConversationId, Guid? UserId, List<HistoryEntry> History);

    private static bool IsAnonymousCaller() =>
        string.IsNullOrEmpty(RequestContext.CurrentUserEmail)
        || string.Equals(RequestContext.CurrentUserRole, "anonymous", StringComparison.OrdinalIgnoreCase);

    /// <summary>
    /// Converts persisted/anonymous history (already ending with the current turn —
    /// see <see cref="PrepareConversationAsync"/>) into the message list the agent
    /// actually reasons over. Mirrors Python's <c>_history_as_maf_messages</c>
    /// role filter, minus its trailing re-append of the current message (see the
    /// plan's disclosed deviation: history here already ends with the current turn).
    /// </summary>
    private static List<ChatMessage> BuildMessages(IReadOnlyList<HistoryEntry> history) =>
        history
            .Where(h => h.Role is "user" or "assistant")
            .Select(h => new ChatMessage(h.Role == "assistant" ? ChatRole.Assistant : ChatRole.User, h.Content))
            .ToList();

    /// <summary>
    /// Mirrors Python's <c>if not is_anon: resolve-or-create conversation → save
    /// user message → load history</c> block (routes.py:363-416 / :485-523).
    /// Anonymous callers skip every DB write and simply echo back whatever
    /// conversation_id the client sent, with empty history — nothing is ever
    /// created for an anonymous chat to persist against.
    /// </summary>
    private static async Task<(ConversationContext? Context, IResult? Error)> PrepareConversationAsync(
        DatabasePool pool,
        string message,
        string? requestedConversationId
    )
    {
        if (IsAnonymousCaller())
        {
            return (
                new ConversationContext(
                    true,
                    requestedConversationId ?? "",
                    null,
                    new List<HistoryEntry> { new HistoryEntry("user", message) }
                ),
                null
            );
        }

        await using var conn = await pool.OpenAsync();
        var userId = await UserResolver.ResolveUserIdAsync(conn, RequestContext.CurrentUserEmail);
        if (userId is null)
        {
            return (null, Results.Unauthorized());
        }

        Guid convId;
        if (!string.IsNullOrWhiteSpace(requestedConversationId))
        {
            if (!Guid.TryParse(requestedConversationId, out convId))
            {
                return (null, Results.NotFound(new { detail = "Conversation not found" }));
            }
            var exists = await conn.ExecuteScalarAsync<bool>(
                "SELECT EXISTS(SELECT 1 FROM conversations WHERE id = @id AND user_id = @uid AND is_active = TRUE)",
                new { id = convId, uid = userId }
            );
            if (!exists)
            {
                return (null, Results.NotFound(new { detail = "Conversation not found" }));
            }
        }
        else
        {
            var title = message.Length > 100 ? message[..100] : message;
            convId = await conn.ExecuteScalarAsync<Guid>(
                "INSERT INTO conversations (user_id, title) VALUES (@uid, @title) RETURNING id",
                new { uid = userId, title }
            );
        }

        await conn.ExecuteAsync(
            "INSERT INTO messages (conversation_id, role, content, agent_name) VALUES (@cid, 'user', @content, NULL)",
            new { cid = convId, content = message }
        );

        var history = (await conn.QueryAsync(
            "SELECT role, content FROM messages WHERE conversation_id = @cid ORDER BY created_at ASC LIMIT 50",
            new { cid = convId }
        )).Select(r => new HistoryEntry((string)r.role, (string)r.content)).ToList();

        return (new ConversationContext(false, convId.ToString(), userId, history), null);
    }

    /// <summary>
    /// Mirrors Python's post-response block: save the assistant message +
    /// bump <c>conversations.last_message_at</c> + log usage (routes.py:436-455 /
    /// :662-678). No-op entirely for anonymous callers — there's no conversation
    /// to write to.
    /// </summary>
    private static async Task PersistAssistantMessageAsync(
        DatabasePool pool,
        UsageRecorder usage,
        ConversationContext ctx,
        string userMessage,
        string responseText,
        List<string> agentsInvolved,
        int durationMs,
        Dictionary<string, object>? metadata = null
    )
    {
        if (ctx.IsAnon)
        {
            return;
        }

        var convId = Guid.Parse(ctx.ConversationId);

        await using (var conn = await pool.OpenAsync())
        {
            await conn.ExecuteAsync(
                @"INSERT INTO messages (conversation_id, role, content, agent_name, agents_involved, metadata)
                  VALUES (@cid, 'assistant', @content, 'orchestrator', @agents, @meta::jsonb)",
                new
                {
                    cid = convId,
                    content = responseText,
                    agents = agentsInvolved.ToArray(),
                    meta = JsonSerializer.Serialize(metadata ?? new Dictionary<string, object>()),
                }
            );
            await conn.ExecuteAsync(
                "UPDATE conversations SET last_message_at = NOW() WHERE id = @cid",
                new { cid = convId }
            );
        }

        await usage.LogAgentUsageAsync(
            ctx.UserId,
            "orchestrator",
            inputSummary: userMessage,
            durationMs: durationMs,
            toolCallsCount: agentsInvolved.Count - 1
        );
    }
}
