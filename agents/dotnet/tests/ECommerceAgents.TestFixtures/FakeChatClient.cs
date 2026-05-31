using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace ECommerceAgents.TestFixtures;

/// <summary>
/// Deterministic chat client for tests. Queues a list of canned responses; each call pops the next one.
/// Replaces MAF's <c>IChatClient</c> in unit tests so no real LLM call is made.
/// </summary>
/// <remarks>
/// Minimal stub implementation — MAF's IChatClient contract is documented in
/// <c>docs/architecture.md</c>. For enhancement plans see <c>.claude/plans/enhancements/</c>.
/// </remarks>
public sealed class FakeChatClient
{
    private readonly Queue<string> _responses = new();

    public int CallCount { get; private set; }

    public IReadOnlyList<string> ReceivedPrompts => _receivedPrompts;
    private readonly List<string> _receivedPrompts = new();

    public FakeChatClient EnqueueResponse(string response)
    {
        _responses.Enqueue(response);
        return this;
    }

    public Task<string> CompleteAsync(string prompt, CancellationToken cancellationToken = default)
    {
        CallCount++;
        _receivedPrompts.Add(prompt);

        if (_responses.Count == 0)
        {
            throw new System.InvalidOperationException(
                "FakeChatClient has no enqueued responses. Call EnqueueResponse before invoking.");
        }

        return Task.FromResult(_responses.Dequeue());
    }
}
