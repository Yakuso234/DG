using Dapper;
using ECommerceAgents.Orchestrator.Routes;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Data;
using ECommerceAgents.TestFixtures;
using FluentAssertions;
using System.Net;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using Xunit;

namespace ECommerceAgents.Orchestrator.Tests;

/// <summary>
/// Covers <see cref="AuthRoutes"/> in both <c>AuthMode=local</c> (unchanged
/// HS256 behavior) and <c>AuthMode=oauth</c> (broker to the self-hosted
/// auth-server). The AS itself is stubbed via <see cref="StaticResponseHandler"/>
/// — these are route-level tests, not a live-AS integration test.
/// </summary>
[Collection(nameof(LocalPostgresCollection))]
public sealed class AuthRoutesTests : IAsyncLifetime
{
    private readonly PostgresFixture _pg;
    private DatabasePool _pool = null!;
    private const string Email = "authroutes@example.com";
    private const string Password = "correct horse battery staple";

    public AuthRoutesTests(PostgresFixture pg) => _pg = pg;

    public async Task InitializeAsync()
    {
        var settings = new AgentSettings { DatabaseUrl = _pg.ConnectionString };
        _pool = new DatabasePool(settings);

        await using var conn = await _pool.OpenAsync();
        await conn.ExecuteAsync(
            @"TRUNCATE order_status_history, order_items, returns, orders,
                       messages, conversations, warehouse_inventory,
                       warehouses, reviews, products, users
              RESTART IDENTITY CASCADE"
        );

        var passwordHash = BCrypt.Net.BCrypt.HashPassword(Password);
        await conn.ExecuteAsync(
            "INSERT INTO users (email, password_hash, name, role) VALUES (@email, @passwordHash, 'Auth Tester', 'customer')",
            new { email = Email, passwordHash }
        );
    }

    public async Task DisposeAsync() => await _pool.DisposeAsync();

    private HttpClient ClientFor(AgentSettings? settings = null, HttpMessageHandler? authServerHandler = null)
    {
        var server = OrchestratorTestHost.Create(_pool, r => r.MapAuthRoutes(), settings, authServerHandler);
        return server.CreateClient();
    }

    // ─────────────────────── local mode (default, unchanged) ─

    [Fact]
    public async Task Signup_CreatesUserAndReturnsTokens()
    {
        using var client = ClientFor();
        var response = await client.PostAsJsonAsync(
            "/api/auth/signup",
            new { email = "newbie@example.com", password = "hunter2hunter2", full_name = "New Bie" }
        );

        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("access_token").GetString().Should().NotBeNullOrEmpty();
        payload.GetProperty("refresh_token").GetString().Should().NotBeNullOrEmpty();
        payload.GetProperty("role").GetString().Should().Be("customer");
    }

    [Fact]
    public async Task Signup_ConflictsOnDuplicateEmail()
    {
        using var client = ClientFor();
        var response = await client.PostAsJsonAsync(
            "/api/auth/signup",
            new { email = Email, password = "hunter2hunter2", full_name = "Dup" }
        );
        response.StatusCode.Should().Be(HttpStatusCode.Conflict);
    }

    [Fact]
    public async Task Login_LocalMode_ReturnsTokensForValidCredentials()
    {
        using var client = ClientFor();
        var response = await client.PostAsJsonAsync("/api/auth/login", new { email = Email, password = Password });

        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("access_token").GetString().Should().NotBeNullOrEmpty();
        payload.GetProperty("email").GetString().Should().Be(Email);
        payload.GetProperty("role").GetString().Should().Be("customer");
    }

    [Fact]
    public async Task Login_LocalMode_RejectsWrongPassword()
    {
        using var client = ClientFor();
        var response = await client.PostAsJsonAsync("/api/auth/login", new { email = Email, password = "wrong" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task Refresh_LocalMode_IssuesNewAccessToken()
    {
        using var client = ClientFor();
        var login = await client.PostAsJsonAsync("/api/auth/login", new { email = Email, password = Password });
        var loginPayload = await login.Content.ReadFromJsonAsync<JsonElement>();
        var refreshToken = loginPayload.GetProperty("refresh_token").GetString();

        var response = await client.PostAsJsonAsync("/api/auth/refresh", new { refresh_token = refreshToken });
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("access_token").GetString().Should().NotBeNullOrEmpty();
    }

    [Fact]
    public async Task Refresh_LocalMode_RejectsGarbageToken()
    {
        using var client = ClientFor();
        var response = await client.PostAsJsonAsync("/api/auth/refresh", new { refresh_token = "not-a-jwt" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    // ─────────────────────── oauth mode (AS-brokered) ────────

    private static AgentSettings OAuthSettings() => new()
    {
        AuthMode = "oauth",
        AuthServerTokenUrl = "http://auth-server:8090/oauth/token",
    };

    [Fact]
    public async Task Login_OAuthMode_BrokersRopcAndReturnsAsTokens()
    {
        var handler = new StaticResponseHandler(
            HttpStatusCode.OK,
            """{"access_token":"as-access-token","refresh_token":"as-refresh-token","token_type":"Bearer","expires_in":3600,"scope":"api:chat"}"""
        );
        using var client = ClientFor(OAuthSettings(), handler);

        var response = await client.PostAsJsonAsync("/api/auth/login", new { email = Email, password = Password });

        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("access_token").GetString().Should().Be("as-access-token");
        payload.GetProperty("refresh_token").GetString().Should().Be("as-refresh-token");
        payload.GetProperty("role").GetString().Should().Be("customer");
        payload.GetProperty("email").GetString().Should().Be(Email);
    }

    [Fact]
    public async Task Login_OAuthMode_PropagatesAuthServerRejection()
    {
        var handler = new StaticResponseHandler(HttpStatusCode.Unauthorized, """{"error":"invalid_grant"}""");
        using var client = ClientFor(OAuthSettings(), handler);

        var response = await client.PostAsJsonAsync("/api/auth/login", new { email = Email, password = "wrong" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task Login_OAuthMode_RejectsWhenUserRowMissingDespiteAsAcceptance()
    {
        var handler = new StaticResponseHandler(
            HttpStatusCode.OK,
            """{"access_token":"as-access-token","refresh_token":"as-refresh-token","token_type":"Bearer","expires_in":3600,"scope":"api:chat"}"""
        );
        using var client = ClientFor(OAuthSettings(), handler);

        var response = await client.PostAsJsonAsync(
            "/api/auth/login",
            new { email = "ghost@example.com", password = Password }
        );
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task Refresh_OAuthMode_ReturnsOnlyAccessToken()
    {
        var handler = new StaticResponseHandler(
            HttpStatusCode.OK,
            """{"access_token":"new-access-token","token_type":"Bearer","expires_in":3600,"scope":"api:chat"}"""
        );
        using var client = ClientFor(OAuthSettings(), handler);

        var response = await client.PostAsJsonAsync(
            "/api/auth/refresh",
            new { refresh_token = "some-opaque-refresh-token" }
        );
        response.EnsureSuccessStatusCode();
        var payload = await response.Content.ReadFromJsonAsync<JsonElement>();
        payload.GetProperty("access_token").GetString().Should().Be("new-access-token");
        payload.TryGetProperty("refresh_token", out _).Should().BeFalse();
    }

    [Fact]
    public async Task Refresh_OAuthMode_PropagatesAuthServerRejection()
    {
        var handler = new StaticResponseHandler(HttpStatusCode.Unauthorized, """{"error":"invalid_grant"}""");
        using var client = ClientFor(OAuthSettings(), handler);

        var response = await client.PostAsJsonAsync("/api/auth/refresh", new { refresh_token = "stale-token" });
        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    private sealed class StaticResponseHandler(HttpStatusCode status, string body) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) =>
            Task.FromResult(new HttpResponseMessage(status)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json"),
            });
    }
}
