using ECommerceAgents.Shared.Configuration;
using FluentAssertions;
using Microsoft.Extensions.Configuration;
using Xunit;

namespace ECommerceAgents.Shared.Tests;

/// <summary>
/// Covers a real bug found while live-verifying the .NET docker-compose
/// stack: <c>docker-compose.dotnet.yml</c> supplies Redis via
/// <c>ConnectionStrings__Redis</c> (double-underscore env-var binding,
/// same convention already used for Postgres), but the loader previously
/// read only the <c>REDIS_URL</c> env var — so the compose-supplied value
/// was silently never picked up. Mirrors <see cref="AgentSettings.DatabaseUrl"/>'s
/// existing (and already-correct) precedence.
/// </summary>
public sealed class AgentSettingsLoaderTests
{
    [Fact]
    public void Load_PrefersConnectionStringsRedis_OverRedisUrlEnvVar()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["ConnectionStrings:Redis"] = "redis:6379" })
            .Build();

        var settings = AgentSettingsLoader.Load(config);

        settings.RedisUrl.Should().Be("redis:6379");
    }

    [Fact]
    public void Load_FallsBackToDefault_WhenNeitherIsSet()
    {
        var config = new ConfigurationBuilder().Build();

        var settings = AgentSettingsLoader.Load(config);

        settings.RedisUrl.Should().Be("redis://localhost:6379");
    }

    [Fact]
    public void Load_TemperatureDefaultsTo0_2_MirroringPython()
    {
        var config = new ConfigurationBuilder().Build();

        var settings = AgentSettingsLoader.Load(config);

        settings.Temperature.Should().Be(0.2);
    }

    [Fact]
    public void Load_ReadsTemperatureFromLlmTemperatureEnvVar()
    {
        var config = new ConfigurationBuilder()
            .AddInMemoryCollection(new Dictionary<string, string?> { ["LLM_TEMPERATURE"] = "0.7" })
            .Build();

        var settings = AgentSettingsLoader.Load(config);

        settings.Temperature.Should().Be(0.7);
    }
}
