using ECommerceAgents.Shared.Auth;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Data;
using ECommerceAgents.TestFixtures;
using FluentAssertions;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using System.IdentityModel.Tokens.Jwt;
using System.Net;
using System.Net.Http.Json;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;

namespace ECommerceAgents.Mcp.Tests;

/// <summary>
/// Phase D: OAuth 2.1 resource-server mode for <see cref="McpEndpoints"/>.
/// Real per-test RSA keypair + <see cref="TestServer"/>, JWKS-serving
/// <see cref="HttpMessageHandler"/> stubbed (no real network call) — same
/// convention as the orchestrator/agent-side
/// <c>AgentAuthMiddlewareInterAgentTests.cs</c>. Zero prior test coverage
/// existed for this endpoint's auth at all before this phase.
/// </summary>
[Collection(nameof(LocalPostgresCollection))]
public sealed class McpAuthTests : IAsyncLifetime
{
    private readonly PostgresFixture _pg;
    private DatabasePool _pool = null!;

    public McpAuthTests(PostgresFixture pg) => _pg = pg;

    public Task InitializeAsync()
    {
        var settings = new AgentSettings { DatabaseUrl = _pg.ConnectionString };
        _pool = new DatabasePool(settings);
        return Task.CompletedTask;
    }

    public async Task DisposeAsync() => await _pool.DisposeAsync();

    private static (RsaSecurityKey key, string kid) NewRsaKey()
    {
        var rsa = RSA.Create(2048);
        var kid = Guid.NewGuid().ToString("N");
        return (new RsaSecurityKey(rsa) { KeyId = kid }, kid);
    }

    private static string IssueToken(
        RsaSecurityKey key,
        string issuer,
        string audience,
        string scope,
        DateTime? expires = null
    )
    {
        var handler = new JwtSecurityTokenHandler();
        var creds = new SigningCredentials(key, SecurityAlgorithms.RsaSha256);
        var token = new JwtSecurityToken(
            issuer: issuer,
            audience: audience,
            claims: new[] { new Claim("scope", scope) },
            notBefore: DateTime.UtcNow.AddMinutes(-30),
            expires: expires ?? DateTime.UtcNow.AddMinutes(5),
            signingCredentials: creds
        );
        return handler.WriteToken(token);
    }

    private static string BuildJwksJson(RsaSecurityKey key)
    {
        var parameters = key.Rsa!.ExportParameters(false);
        var n = Base64UrlEncoder.Encode(parameters.Modulus);
        var e = Base64UrlEncoder.Encode(parameters.Exponent);
        return $$"""{"keys":[{"kty":"RSA","use":"sig","kid":"{{key.KeyId}}","alg":"RS256","n":"{{n}}","e":"{{e}}"}]}""";
    }

    private sealed class StaticResponseHandler(string body) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) =>
            Task.FromResult(
                new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent(body, Encoding.UTF8, "application/json"),
                }
            );
    }

    private static AgentSettings SettingsFor() =>
        new()
        {
            AgentSharedSecret = new string('s', 48),
            JwtSecret = new string('j', 48),
            Environment = "test",
            McpAuthEnabled = true,
            AuthServerIssuer = "http://auth-server:8090",
            McpAudience = "mcp-inventory",
            McpRequiredScope = "mcp:inventory",
            McpResourceUrl = "http://localhost:9001/mcp",
        };

    private TestServer BuildServer(AgentSettings settings, RsaSecurityKey key)
    {
        var hostBuilder = new HostBuilder().ConfigureWebHost(web =>
        {
            web.UseTestServer();
            web.ConfigureServices(services =>
            {
                services.AddSingleton(_pool);
                services.AddSingleton(settings);
                services.AddSingleton(new JwtTokenService(settings));
                services.AddSingleton(
                    new JwksKeyProvider(new HttpClient(new StaticResponseHandler(BuildJwksJson(key))), settings)
                );
                services.AddRouting();
            });
            web.Configure(app =>
            {
                app.UseRouting();
                app.UseEndpoints(endpoints => endpoints.MapMcpEndpoints());
            });
        });

        return hostBuilder.Start().GetTestServer();
    }

    [Fact]
    public async Task ExecuteTool_RejectsMissingToken()
    {
        var (key, _) = NewRsaKey();
        using var server = BuildServer(SettingsFor(), key);
        using var client = server.CreateClient();

        var response = await client.PostAsync("/mcp/tools/get_warehouses", null);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
        response.Headers.WwwAuthenticate.ToString().Should().Contain("invalid_token");
    }

    [Fact]
    public async Task ExecuteTool_AcceptsValidToken()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor();
        var token = IssueToken(key, settings.AuthServerIssuer, settings.McpAudience, settings.McpRequiredScope);
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp/tools/get_warehouses");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }

    [Fact]
    public async Task ExecuteTool_RejectsWrongAudience()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor();
        var token = IssueToken(key, settings.AuthServerIssuer, "mcp-product", settings.McpRequiredScope);
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp/tools/get_warehouses");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task ExecuteTool_RejectsWrongScope()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor();
        var token = IssueToken(key, settings.AuthServerIssuer, settings.McpAudience, "mcp:product");
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp/tools/get_warehouses");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task ExecuteTool_RejectsExpiredToken()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor();
        var token = IssueToken(
            key,
            settings.AuthServerIssuer,
            settings.McpAudience,
            settings.McpRequiredScope,
            expires: DateTime.UtcNow.AddMinutes(-10)
        );
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var request = new HttpRequestMessage(HttpMethod.Post, "/mcp/tools/get_warehouses");
        request.Headers.Add("Authorization", $"Bearer {token}");
        var response = await client.SendAsync(request);

        response.StatusCode.Should().Be(HttpStatusCode.Unauthorized);
    }

    [Fact]
    public async Task McpAuthDisabled_AllowsUnauthenticatedCall()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor() with { McpAuthEnabled = false };
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var response = await client.PostAsync("/mcp/tools/get_warehouses", null);

        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }

    [Fact]
    public async Task ProtectedResourceMetadata_ReturnsCorrectShape()
    {
        var (key, _) = NewRsaKey();
        var settings = SettingsFor();
        using var server = BuildServer(settings, key);
        using var client = server.CreateClient();

        var response = await client.GetAsync("/.well-known/oauth-protected-resource");

        response.StatusCode.Should().Be(HttpStatusCode.OK);
        var body = await response.Content.ReadFromJsonAsync<JsonElement>();
        body.GetProperty("resource").GetString().Should().Be(settings.McpResourceUrl);
        body.GetProperty("authorization_servers")[0].GetString().Should().Be(settings.AuthServerIssuer);
        body.GetProperty("scopes_supported")[0].GetString().Should().Be(settings.McpRequiredScope);
    }

    [Fact]
    public async Task ProtectedResourceMetadata_IsUnauthenticatedEvenWithAuthEnabled()
    {
        var (key, _) = NewRsaKey();
        using var server = BuildServer(SettingsFor(), key);
        using var client = server.CreateClient();

        var response = await client.GetAsync("/.well-known/oauth-protected-resource");

        response.StatusCode.Should().Be(HttpStatusCode.OK);
    }
}
