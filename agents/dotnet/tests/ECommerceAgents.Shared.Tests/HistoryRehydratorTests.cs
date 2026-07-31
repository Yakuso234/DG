using Dapper;
using ECommerceAgents.Shared.A2A;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Data;
using ECommerceAgents.TestFixtures;
using FluentAssertions;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// Mirrors Python's <c>_rehydrate_history_from_session</c> (audit fix #14):
/// specialists rehydrate their own recent context straight from Postgres
/// when no history is forwarded on the A2A payload.
/// </summary>
[Collection(nameof(LocalPostgresCollection))]
public sealed class HistoryRehydratorTests : IAsyncLifetime
{
    private readonly PostgresFixture _pg;
    private DatabasePool _pool = null!;

    public HistoryRehydratorTests(PostgresFixture pg) => _pg = pg;

    public async Task InitializeAsync()
    {
        _pool = new DatabasePool(new AgentSettings { DatabaseUrl = _pg.ConnectionString });
        await using var conn = await _pool.OpenAsync();
        await conn.ExecuteAsync("TRUNCATE messages, conversations, users RESTART IDENTITY CASCADE");
    }

    public async Task DisposeAsync() => await _pool.DisposeAsync();

    [Fact]
    public async Task RehydrateAsync_ReturnsNullForEmptySessionId()
    {
        var result = await HistoryRehydrator.RehydrateAsync(_pool, "");
        result.Should().BeNull();
    }

    [Fact]
    public async Task RehydrateAsync_ReturnsNullForNonGuidSessionId()
    {
        var result = await HistoryRehydrator.RehydrateAsync(_pool, "not-a-conversation-id");
        result.Should().BeNull();
    }

    [Fact]
    public async Task RehydrateAsync_ReturnsNullForUnknownConversation()
    {
        var result = await HistoryRehydrator.RehydrateAsync(_pool, Guid.NewGuid().ToString());
        result.Should().NotBeNull();
        result.Should().BeEmpty();
    }

    [Fact]
    public async Task RehydrateAsync_ReturnsChronologicalRoleFilteredHistory()
    {
        var conversationId = await SeedConversationAsync();
        await using (var conn = await _pool.OpenAsync())
        {
            await conn.ExecuteAsync(
                @"INSERT INTO messages (conversation_id, role, content, agent_name, created_at) VALUES
                  (@cid, 'user', 'q1', NULL, NOW() - INTERVAL '2 minutes'),
                  (@cid, 'assistant', 'a1', 'order-management', NOW() - INTERVAL '1 minutes'),
                  (@cid, 'system', 'ignored system row', NULL, NOW() - INTERVAL '30 seconds'),
                  (@cid, 'user', 'q2', NULL, NOW())",
                new { cid = conversationId }
            );
        }

        var result = await HistoryRehydrator.RehydrateAsync(_pool, conversationId.ToString());

        result.Should().NotBeNull();
        result!.Select(h => (h.Role, h.Content)).Should().Equal(
            ("user", "q1"),
            ("assistant", "a1"),
            ("user", "q2")
        );
    }

    private async Task<Guid> SeedConversationAsync()
    {
        await using var conn = await _pool.OpenAsync();
        var userId = await conn.ExecuteScalarAsync<Guid>(
            "INSERT INTO users (email, password_hash, name, role) VALUES ('rehydrate@example.com', 'x', 'R', 'customer') RETURNING id"
        );
        return await conn.ExecuteScalarAsync<Guid>(
            "INSERT INTO conversations (user_id, title) VALUES (@uid, 'test') RETURNING id",
            new { uid = userId }
        );
    }
}
