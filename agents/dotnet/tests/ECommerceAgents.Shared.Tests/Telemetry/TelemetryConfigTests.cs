using ECommerceAgents.Shared.Telemetry;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using OpenTelemetry.Metrics;
using OpenTelemetry.Trace;
using Xunit;

namespace ECommerceAgents.Shared.Tests.Telemetry;

// These are unit tests for the telemetry *wiring*: that AddEcommerceTelemetry
// registers the OpenTelemetry tracer/meter providers and parses configuration
// without throwing. We deliberately do NOT eagerly resolve the live
// TracerProvider here — that forces construction of the OTLP gRPC exporter,
// which is environment-dependent (it NREs on Linux/CI when built from a bare
// ServiceCollection with no running collector). Actual exporter delivery is
// integration-level behaviour exercised by the running stack, not a unit test.
public class TelemetryConfigTests
{
    private static IConfiguration BuildConfig(Dictionary<string, string?> values)
    {
        return new ConfigurationBuilder()
            .AddInMemoryCollection(values)
            .Build();
    }

    private static bool IsRegistered<T>(IServiceCollection services)
        => services.Any(d => d.ServiceType == typeof(T));

    [Fact]
    public void Build_DefaultConfiguration_RegistersTracerAndMeterProviders()
    {
        var services = new ServiceCollection();
        services.AddLogging();

        services.AddEcommerceTelemetry(BuildConfig(new Dictionary<string, string?>()), "test-service");

        Assert.True(IsRegistered<TracerProvider>(services));
        Assert.True(IsRegistered<MeterProvider>(services));
    }

    [Fact]
    public void Build_WithConsoleExporter_DoesNotThrow()
    {
        var services = new ServiceCollection();
        services.AddLogging();

        var ex = Record.Exception(() => services.AddEcommerceTelemetry(
            BuildConfig(new Dictionary<string, string?> { ["Otlp:ConsoleExporter"] = "true" }),
            "test-service"));

        Assert.Null(ex);
        Assert.True(IsRegistered<TracerProvider>(services));
    }

    [Fact]
    public void Build_WithCustomEndpoint_DoesNotThrow()
    {
        var services = new ServiceCollection();
        services.AddLogging();

        var ex = Record.Exception(() => services.AddEcommerceTelemetry(
            BuildConfig(new Dictionary<string, string?> { ["Otlp:Endpoint"] = "http://collector:4317" }),
            "test-service"));

        Assert.Null(ex);
        Assert.True(IsRegistered<TracerProvider>(services));
    }

    [Fact]
    public void Build_WithCustomResourceAttributes_DoesNotThrow()
    {
        var services = new ServiceCollection();
        services.AddLogging();

        var ex = Record.Exception(() => services.AddEcommerceTelemetry(
            BuildConfig(new Dictionary<string, string?> { ["Otlp:Environment"] = "production" }),
            "test-service"));

        Assert.Null(ex);
        Assert.True(IsRegistered<MeterProvider>(services));
    }

    [Fact]
    public void Build_ReturnsServiceCollectionForChaining()
    {
        var services = new ServiceCollection();

        var result = services.AddEcommerceTelemetry(
            BuildConfig(new Dictionary<string, string?>()), "test-service");

        Assert.Same(services, result);
    }
}
