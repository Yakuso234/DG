using Dapper;
using ECommerceAgents.Shared.Context;
using ECommerceAgents.Shared.Data;

namespace ECommerceAgents.Shared.A2A;

/// <summary>
/// Mirrors Python's <c>agent_host._rehydrate_history_from_session</c>
/// (audit fix #14): specialists no longer rely solely on a forwarded
/// history payload — when one isn't present, they pull their own recent
/// context straight from Postgres via the session id (= conversation id)
/// header.
/// </summary>
public static class HistoryRehydrator
{
    /// <summary>Kept in lockstep with <c>ChatRoutes.PrepareConversationAsync</c>'s own LIMIT 50.</summary>
    private const int SessionHistoryLimit = 50;

    /// <summary>
    /// Fetches up to <see cref="SessionHistoryLimit"/> recent messages for
    /// <paramref name="sessionId"/> (a conversation UUID). Fail-safe: returns
    /// <c>null</c> on any error (missing/invalid id, DB failure) so the caller
    /// falls back to a no-history run rather than erroring out — matching
    /// Python's behavior exactly.
    /// </summary>
    public static async Task<List<HistoryEntry>?> RehydrateAsync(DatabasePool pool, string sessionId)
    {
        if (string.IsNullOrEmpty(sessionId) || !Guid.TryParse(sessionId, out var conversationId))
        {
            return null;
        }

        try
        {
            await using var conn = await pool.OpenAsync();
            var rows = await conn.QueryAsync(
                @"SELECT role, content FROM messages
                  WHERE conversation_id = @id
                  ORDER BY created_at ASC
                  LIMIT @limit",
                new { id = conversationId, limit = SessionHistoryLimit }
            );
            return rows
                .Where(r => (string)r.role is "user" or "assistant")
                .Select(r => new HistoryEntry((string)r.role, (string)r.content))
                .ToList();
        }
        catch
        {
            return null;
        }
    }
}
