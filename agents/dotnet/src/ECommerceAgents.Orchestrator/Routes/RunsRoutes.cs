using Dapper;
using ECommerceAgents.Shared.Context;
using ECommerceAgents.Shared.Data;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace ECommerceAgents.Orchestrator.Routes;

/// <summary>
/// <c>GET /api/runs</c> — the caller's own recent agent runs with step
/// details; admins see every user's runs. Mirrors Python's <c>list_runs</c>
/// (<c>routes.py:1406-1491</c>). Previously missing entirely from the .NET
/// orchestrator. Distinct from <c>GET /api/admin/audit</c>
/// (<see cref="AdminRoutes.MapAdminRoutes"/>): that one is admin-only with
/// agent_name/status/search filters and includes <c>error_message</c>; this
/// one is scoped by caller identity, has no filters, and — matching
/// Python — omits <c>error_message</c> from each entry.
/// </summary>
public static class RunsRoutes
{
    public static IEndpointRouteBuilder MapRunsRoutes(this IEndpointRouteBuilder routes)
    {
        routes.MapGet("/api/runs", ListRuns);
        return routes;
    }

    private static async Task<IResult> ListRuns(DatabasePool pool, int limit = 20, int offset = 0)
    {
        var email = RequestContext.CurrentUserEmail;
        if (string.IsNullOrEmpty(email))
        {
            return Results.Unauthorized();
        }
        var isAdmin = string.Equals(RequestContext.CurrentUserRole, "admin", StringComparison.OrdinalIgnoreCase);

        int clampedLimit = Math.Clamp(limit, 1, 100);
        int clampedOffset = Math.Max(0, offset);
        var where = isAdmin ? "" : "WHERE ul.user_id = (SELECT id FROM users WHERE email = @email)";

        await using var conn = await pool.OpenAsync();
        var rows = (await conn.QueryAsync(
            $@"SELECT ul.id, ul.agent_name, ul.input_summary, ul.tokens_in, ul.tokens_out,
                      ul.tool_calls_count, ul.duration_ms, ul.status, ul.trace_id, ul.created_at,
                      u.email AS user_email, u.name AS user_name
               FROM usage_logs ul
               LEFT JOIN users u ON ul.user_id = u.id
               {where}
               ORDER BY ul.created_at DESC
               LIMIT @limit OFFSET @offset",
            new { email, limit = clampedLimit, offset = clampedOffset }
        )).ToList();

        var entries = new List<object>();
        foreach (var r in rows)
        {
            var steps = await UsageLogSteps.FetchAsync(conn, (Guid)r.id);
            entries.Add(new
            {
                id = ((Guid)r.id).ToString(),
                agent_name = (string?)r.agent_name,
                user_email = (string?)r.user_email,
                user_name = (string?)r.user_name,
                input_summary = (string?)r.input_summary,
                tokens_in = r.tokens_in is null ? 0 : Convert.ToInt32(r.tokens_in),
                tokens_out = r.tokens_out is null ? 0 : Convert.ToInt32(r.tokens_out),
                tool_calls_count = r.tool_calls_count is null ? 0 : Convert.ToInt32(r.tool_calls_count),
                duration_ms = r.duration_ms is null ? (int?)null : Convert.ToInt32(r.duration_ms),
                status = (string?)r.status,
                trace_id = (string?)r.trace_id,
                created_at = ((DateTime)r.created_at).ToString("o"),
                steps,
            });
        }

        var total = await conn.ExecuteScalarAsync<long>(
            $"SELECT COUNT(*) FROM usage_logs ul {where}",
            new { email }
        );

        return Results.Ok(new { entries, total, limit = clampedLimit, offset = clampedOffset });
    }
}
