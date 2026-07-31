using ECommerceAgents.Orchestrator.Agent;
using ECommerceAgents.Shared.A2A;
using ECommerceAgents.Shared.Auth;
using ECommerceAgents.Shared.Configuration;
using ECommerceAgents.Shared.Context;
using FluentAssertions;
using Microsoft.Extensions.Logging.Abstractions;
using System.Net;
using System.Net.Http.Json;
using System.Text;
using Xunit;

namespace ECommerceAgents.Orchestrator.Tests;

/// <summary>
/// <see cref="OrchestratorTools.CallSpecialistAgent"/>'s side effect on
/// <see cref="RequestContext.CurrentInvokedAgents"/> — backs the streaming
/// chat endpoint's dynamic <c>agents_involved</c> (mirrors Python's
/// <c>current_steps</c> capture, <c>routes.py:651-655</c>). No real network
/// call: the A2A HTTP call is stubbed.
/// </summary>
public sealed class OrchestratorToolsTests
{
    private sealed class StaticResponseHandler(string body) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct) =>
            Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(body, Encoding.UTF8, "application/json"),
            });
    }

    private static OrchestratorTools BuildTools(string agentName = "product-discovery")
    {
        var settings = new AgentSettings
        {
            AgentSharedSecret = new string('s', 48),
            AuthMode = "local",
            AgentRegistry = $$"""{"{{agentName}}":"http://fake-{{agentName}}"}""",
        };
        var http = new HttpClient(new StaticResponseHandler("""{"response":"specialist reply"}"""));
        var a2a = new A2AClient(http, settings, new AuthServerClient(new HttpClient(), settings), NullLogger<A2AClient>.Instance);
        return new OrchestratorTools(a2a, settings, NullLogger<OrchestratorTools>.Instance);
    }

    [Fact]
    public async Task CallSpecialistAgent_RecordsInvocationOnRequestContext()
    {
        var tools = BuildTools("product-discovery");
        using var scope = RequestContext.Scope("alice@example.com", "customer", "sess-1");

        RequestContext.CurrentInvokedAgents.Should().BeEmpty();

        var reply = await tools.CallSpecialistAgent("product-discovery", "find headphones");

        reply.Should().Be("specialist reply");
        RequestContext.CurrentInvokedAgents.Should().ContainSingle().Which.Should().Be("product-discovery");
    }

    [Fact]
    public async Task CallSpecialistAgent_UnknownAgent_DoesNotRecordAndReturnsMessage()
    {
        var tools = BuildTools("product-discovery");
        using var scope = RequestContext.Scope("alice@example.com", "customer", "sess-1");

        var reply = await tools.CallSpecialistAgent("not-a-real-agent", "hi");

        reply.Should().Contain("Unknown agent");
        RequestContext.CurrentInvokedAgents.Should().BeEmpty();
    }

    [Fact]
    public async Task CallSpecialistAgent_MultipleCalls_RecordEachInvocation()
    {
        var tools = BuildTools("order-management");
        using var scope = RequestContext.Scope("alice@example.com", "customer", "sess-1");

        await tools.CallSpecialistAgent("order-management", "cancel order 123");
        await tools.CallSpecialistAgent("order-management", "what's the status");

        RequestContext.CurrentInvokedAgents.Should().Equal("order-management", "order-management");
    }
}
