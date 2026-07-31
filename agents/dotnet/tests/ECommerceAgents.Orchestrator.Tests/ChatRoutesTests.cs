using Dapper;
using ECommerceAgents.Orchestrator.Routes;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Data;
using ECommerceAgents.Shared.Telemetry;
using ECommerceAgents.TestFixtures;
using FluentAssertions;
using Microsoft.AspNetCore.Routing;
using Microsoft.Agents.AI;
using Microsoft.Extensions.AI;
using Microsoft.Extensions.DependencyInjection;
using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Xunit;

namespace ECommerceAgents.Orchestrator.Tests;

/// <summary>
/// <see cref="ChatRoutes"/>'s conversation persistence — the core Phase 2
/// fix. Previously the .NET orchestrator never wrote to
/// <c>conversations</c>/<c>messages</c> at all, so <c>GET /api/conversations</c>
/// was permanently empty and the response shape omitted <c>conversation_id</c>/
/// <c>agents_involved</c> that the frontend's TS types require as non-optional.
/// Uses a real Postgres testcontainer (via <see cref="LocalPostgresCollection"/>,
/// already defined in <see cref="OrchestratorRouteTests"/>) and a
/// <see cref="FakeChatClient"/>-backed <c>AIAgent</c> — no real LLM call.
/// </summary>
[Collection(nameof(LocalPostgresCollection))]
public sealed class ChatRoutesTests : IAsyncLifetime
{
    private readonly PostgresFixture _pg;
    private DatabasePool _pool = null!;
    private const string Email = "chatroutes@example.com";

    public ChatRoutesTests(PostgresFixture pg) => _pg = pg;

    public async Task InitializeAsync()
    {
        var settings = new AgentSettings { DatabaseUrl = _pg.ConnectionString };
        _pool = new DatabasePool(settings);

        await using var conn = await _pool.OpenAsync();
        await conn.ExecuteAsync(
            @"TRUNCATE order_status_history, order_items, returns, orders,
                       messages, conversations, warehouse_inventory,
                       warehouses, reviews, products, users, usage_logs
              RESTART IDENTITY CASCADE"
        );
        await conn.ExecuteAsync(
            "INSERT INTO users (email, password_hash, name, role) VALUES (@email, 'x', 'Chat Tester', 'customer')",
            new { email = Email }
        );
    }

    public async Task DisposeAsync() => await _pool.DisposeAsync();

    private HttpClient ClientFor(FakeChatClient chatClient, bool authenticated = true)
    {
        var server = OrchestratorTestHost.Create(
            _pool,
            r =>
            {
                r.MapChatRoutes();
                r.MapConversationRoutes();
            },
            configureServices: services =>
            {
                services.AddSingleton<IChatClient>(chatClient);
                services.AddSingleton<AIAgent>(sp =>
                    sp.GetRequiredService<IChatClient>().AsAIAgent(instructions: "test instructions", name: "orchestrator")
                );
                services.AddSingleton<UsageRecorder>();
            }
        );
        var client = server.CreateClient();
        if (authenticated)
        {
            client.DefaultRequestHeaders.Add("X-Test-Email", Email);
        }
        return client;
    }

    // ─────────────────────── blocking chat ───────────────────

    [Fact]
    public async Task SendAsync_Authenticated_CreatesConversationAndPersistsBothMessages()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("Hi! Here are some headphones."));

        var response = await client.PostAsJsonAsync("/api/chat", new { message = "Find me headphones" });
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();

        payload.GetProperty("response").GetString().Should().Be("Hi! Here are some headphones.");
        var conversationId = payload.GetProperty("conversation_id").GetString();
        conversationId.Should().NotBeNullOrEmpty();
        payload.GetProperty("agents_involved").EnumerateArray().Select(e => e.GetString())
            .Should().Equal("orchestrator");

        var convos = await client.GetFromJsonAsync<JsonElement>("/api/conversations");
        convos.GetArrayLength().Should().Be(1);
        convos[0].GetProperty("id").GetString().Should().Be(conversationId);
        convos[0].GetProperty("message_count").GetInt32().Should().Be(2); // user + assistant
    }

    [Fact]
    public async Task SendAsync_SecondTurn_AppendsToSameConversation()
    {
        using var client = ClientFor(
            new FakeChatClient().EnqueueResponse("first reply").EnqueueResponse("second reply")
        );

        var first = await client.PostAsJsonAsync("/api/chat", new { message = "hello" });
        var firstPayload = await first.Content.ReadFromJsonAsync<JsonElement>();
        var conversationId = firstPayload.GetProperty("conversation_id").GetString();

        var second = await client.PostAsJsonAsync(
            "/api/chat",
            new { message = "follow up", conversation_id = conversationId }
        );
        second.EnsureSuccessStatusCode();
        var secondPayload = await second.Content.ReadFromJsonAsync<JsonElement>();
        secondPayload.GetProperty("conversation_id").GetString().Should().Be(conversationId);

        var detail = await client.GetFromJsonAsync<JsonElement>($"/api/conversations/{conversationId}");
        detail.GetProperty("messages").GetArrayLength().Should().Be(4); // 2 user + 2 assistant turns
    }

    [Fact]
    public async Task SendAsync_FirstTurn_SendsSingleMessageHistoryToAgent()
    {
        var chatClient = new FakeChatClient().EnqueueResponse("first reply");
        using var client = ClientFor(chatClient);

        await client.PostAsJsonAsync("/api/chat", new { message = "hello" });

        chatClient.ReceivedMessages.Should().HaveCount(1);
        var messages = chatClient.ReceivedMessages[0].ToList();
        messages.Should().HaveCount(1);
        messages[0].Role.Should().Be(ChatRole.User);
        messages[0].Text.Should().Be("hello");
    }

    [Fact]
    public async Task SendAsync_SecondTurn_ForwardsFullPriorHistoryToAgent()
    {
        var chatClient = new FakeChatClient().EnqueueResponse("first reply").EnqueueResponse("second reply");
        using var client = ClientFor(chatClient);

        var first = await client.PostAsJsonAsync("/api/chat", new { message = "hello" });
        var firstPayload = await first.Content.ReadFromJsonAsync<JsonElement>();
        var conversationId = firstPayload.GetProperty("conversation_id").GetString();

        await client.PostAsJsonAsync(
            "/api/chat",
            new { message = "follow up", conversation_id = conversationId }
        );

        chatClient.ReceivedMessages.Should().HaveCount(2);
        var secondCallMessages = chatClient.ReceivedMessages[1].ToList();
        secondCallMessages.Select(m => (m.Role, m.Text)).Should().Equal(
            (ChatRole.User, "hello"),
            (ChatRole.Assistant, "first reply"),
            (ChatRole.User, "follow up")
        );
    }

    [Fact]
    public async Task SendAsync_Anonymous_SendsSingleMessageHistoryToAgent()
    {
        var chatClient = new FakeChatClient().EnqueueResponse("anonymous reply");
        using var client = ClientFor(chatClient, authenticated: false);

        await client.PostAsJsonAsync("/api/chat", new { message = "browsing without an account" });

        chatClient.ReceivedMessages.Should().HaveCount(1);
        var messages = chatClient.ReceivedMessages[0].ToList();
        messages.Should().HaveCount(1);
        messages[0].Role.Should().Be(ChatRole.User);
        messages[0].Text.Should().Be("browsing without an account");
    }

    [Fact]
    public async Task SendAsync_UnknownConversationId_ReturnsNotFound()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("unused"));

        var response = await client.PostAsJsonAsync(
            "/api/chat",
            new { message = "hi", conversation_id = Guid.NewGuid().ToString() }
        );

        response.StatusCode.Should().Be(HttpStatusCode.NotFound);
    }

    [Fact]
    public async Task SendAsync_Anonymous_PersistsNothingButStillResponds()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("anonymous reply"), authenticated: false);

        var response = await client.PostAsJsonAsync("/api/chat", new { message = "browsing without an account" });
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("response").GetString().Should().Be("anonymous reply");
        payload.GetProperty("conversation_id").GetString().Should().BeEmpty();

        await using var conn = await _pool.OpenAsync();
        var conversationCount = await conn.ExecuteScalarAsync<long>("SELECT COUNT(*) FROM conversations");
        var messageCount = await conn.ExecuteScalarAsync<long>("SELECT COUNT(*) FROM messages");
        conversationCount.Should().Be(0);
        messageCount.Should().Be(0);
    }

    [Fact]
    public async Task SendAsync_Authenticated_LogsUsage()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("logged reply"));

        await client.PostAsJsonAsync("/api/chat", new { message = "log this" });

        await using var conn = await _pool.OpenAsync();
        var status = await conn.ExecuteScalarAsync<string?>(
            "SELECT status FROM usage_logs WHERE agent_name = 'orchestrator'"
        );
        status.Should().Be("success");
    }

    // ─────────────────────── streaming chat ──────────────────

    [Fact]
    public async Task StreamAsync_EmitsMetadataEventAndPersistsAssistantMessage()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("streamed reply"));

        var response = await client.PostAsJsonAsync("/api/chat/stream", new { message = "stream this" });
        response.EnsureSuccessStatusCode();
        var body = await response.Content.ReadAsStringAsync();

        body.Should().Contain("event: metadata");
        body.Should().Contain("\"agents_involved\":[\"orchestrator\"]");
        body.Should().Contain("data: [DONE]");

        // Parse the conversation_id out of the metadata frame the same way the
        // frontend does, and confirm the turn was actually persisted.
        var metadataLine = body.Split("\n\n").First(e => e.Contains("event: metadata"));
        var dataLine = metadataLine.Split('\n').First(l => l.StartsWith("data: "))["data: ".Length..];
        var metadata = JsonSerializer.Deserialize<JsonElement>(dataLine);
        var conversationId = metadata.GetProperty("conversation_id").GetString();
        conversationId.Should().NotBeNullOrEmpty();

        var detail = await client.GetFromJsonAsync<JsonElement>($"/api/conversations/{conversationId}");
        detail.GetProperty("messages").GetArrayLength().Should().Be(2);
    }

    [Fact]
    public async Task StreamAsync_SecondTurn_ForwardsFullPriorHistoryToAgent()
    {
        var chatClient = new FakeChatClient().EnqueueResponse("first reply").EnqueueResponse("second reply");
        using var client = ClientFor(chatClient);

        var first = await client.PostAsJsonAsync("/api/chat/stream", new { message = "hello" });
        var firstBody = await first.Content.ReadAsStringAsync();
        var firstMetaLine = firstBody.Split("\n\n").First(e => e.Contains("event: metadata"));
        var firstData = firstMetaLine.Split('\n').First(l => l.StartsWith("data: "))["data: ".Length..];
        var conversationId = JsonSerializer.Deserialize<JsonElement>(firstData).GetProperty("conversation_id").GetString();

        await client.PostAsJsonAsync(
            "/api/chat/stream",
            new { message = "follow up", conversation_id = conversationId }
        );

        chatClient.ReceivedMessages.Should().HaveCount(2);
        var secondCallMessages = chatClient.ReceivedMessages[1].ToList();
        secondCallMessages.Select(m => (m.Role, m.Text)).Should().Equal(
            (ChatRole.User, "hello"),
            (ChatRole.Assistant, "first reply"),
            (ChatRole.User, "follow up")
        );
    }

    [Fact]
    public async Task StreamAsync_Anonymous_PersistsNothing()
    {
        using var client = ClientFor(new FakeChatClient().EnqueueResponse("anon stream reply"), authenticated: false);

        var response = await client.PostAsJsonAsync("/api/chat/stream", new { message = "anon streaming" });
        response.EnsureSuccessStatusCode();

        await using var conn = await _pool.OpenAsync();
        var messageCount = await conn.ExecuteScalarAsync<long>("SELECT COUNT(*) FROM messages");
        messageCount.Should().Be(0);
    }
}
