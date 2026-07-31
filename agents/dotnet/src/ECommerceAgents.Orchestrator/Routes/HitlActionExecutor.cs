using Dapper;
using ECommerceAgents.Shared.Data;
using System.Text.Json;

namespace ECommerceAgents.Orchestrator.Routes;

/// <summary>
/// Directly executes a previously admin-approved HITL action without
/// re-running the LLM loop. Mirrors Python's <c>execute_approved_action</c>
/// (<c>shared/hitl.py:254-358</c>) tool_name-keyed dispatch table 1:1 —
/// same DB operations, same success/failure messages. Called by
/// <see cref="HitlRoutes"/>'s approve endpoint.
/// </summary>
internal static class HitlActionExecutor
{
    public static async Task<Dictionary<string, object?>> ExecuteAsync(
        DatabasePool pool,
        string toolName,
        JsonElement toolInput,
        string userEmail
    )
    {
        await using var conn = await pool.OpenAsync();

        switch (toolName)
        {
            case "cancel_order":
            {
                var orderId = GetString(toolInput, "order_id") ?? "";
                if (!Guid.TryParse(orderId, out var orderGuid))
                {
                    return Failure("Order not found or already processed.");
                }
                var row = await conn.QueryFirstOrDefaultAsync(
                    @"UPDATE orders SET status = 'cancelled'
                      WHERE id = @id
                        AND user_id = (SELECT id FROM users WHERE email = @email)
                        AND status IN ('placed', 'confirmed')
                      RETURNING id, status, total",
                    new { id = orderGuid, email = userEmail }
                );
                if (row is null)
                {
                    return Failure("Order not found or already processed.");
                }
                var total = (decimal)row.total;
                return Success(new Dictionary<string, object?>
                {
                    ["order_id"] = orderId,
                    ["new_status"] = "cancelled",
                    ["message"] = $"Order {ShortId(orderId)} cancelled. Refund of ${total:F2} initiated.",
                });
            }

            case "process_refund":
            {
                var orderId = GetString(toolInput, "order_id") ?? "";
                if (!Guid.TryParse(orderId, out var orderGuid))
                {
                    return Failure("Order not found.");
                }
                var row = await conn.QueryFirstOrDefaultAsync(
                    @"UPDATE orders SET status = 'refunded'
                      WHERE id = @id AND user_id = (SELECT id FROM users WHERE email = @email)
                      RETURNING id, total",
                    new { id = orderGuid, email = userEmail }
                );
                if (row is null)
                {
                    return Failure("Order not found.");
                }
                var total = (decimal)row.total;
                return Success(new Dictionary<string, object?>
                {
                    ["refunded_amount"] = total,
                    ["message"] = $"Refund of ${total:F2} processed.",
                });
            }

            case "initiate_return":
            {
                var orderId = GetString(toolInput, "order_id") ?? "";
                var reason = GetString(toolInput, "reason") ?? "Admin-approved return";
                if (!Guid.TryParse(orderId, out var orderGuid))
                {
                    return Failure("Order not found.");
                }
                var returnId = await conn.QueryFirstOrDefaultAsync<Guid?>(
                    @"INSERT INTO returns (order_id, user_id, reason, status, refund_method)
                      SELECT o.id, o.user_id, @reason, 'approved', 'original_payment'
                      FROM orders o JOIN users u ON o.user_id = u.id
                      WHERE o.id = @id AND u.email = @email
                      RETURNING id",
                    new { id = orderGuid, email = userEmail, reason }
                );
                if (returnId is null)
                {
                    return Failure("Order not found.");
                }
                return Success(new Dictionary<string, object?>
                {
                    ["return_id"] = returnId.Value.ToString(),
                    ["message"] = "Return approved and initiated.",
                });
            }

            case "modify_order":
            {
                var orderId = GetString(toolInput, "order_id") ?? "";
                if (!Guid.TryParse(orderId, out var orderGuid))
                {
                    return Failure("Order not found or already shipped.");
                }
                var addressJson = toolInput.ValueKind == JsonValueKind.Object
                    && toolInput.TryGetProperty("new_address", out var addr)
                        ? addr.GetRawText()
                        : "{}";
                var affected = await conn.ExecuteAsync(
                    @"UPDATE orders SET shipping_address = @json::jsonb
                      WHERE id = @id
                        AND user_id = (SELECT id FROM users WHERE email = @email)
                        AND status NOT IN ('shipped', 'delivered', 'cancelled')",
                    new { id = orderGuid, email = userEmail, json = addressJson }
                );
                if (affected == 0)
                {
                    return Failure("Order not found or already shipped.");
                }
                return Success(new Dictionary<string, object?>
                {
                    ["order_id"] = orderId,
                    ["message"] = "Shipping address updated.",
                });
            }

            case "place_backorder":
            {
                var productId = GetString(toolInput, "product_id") ?? "unknown";
                return Success(new Dictionary<string, object?>
                {
                    ["message"] = $"Backorder approved for product {ShortId(productId)}.",
                });
            }

            default:
                return Failure($"Auto-execution not configured for tool: {toolName}");
        }
    }

    private static string ShortId(string id) => id.Length > 8 ? id[..8] : id;

    private static string? GetString(JsonElement input, string key) =>
        input.ValueKind == JsonValueKind.Object
        && input.TryGetProperty(key, out var v)
        && v.ValueKind == JsonValueKind.String
            ? v.GetString()
            : null;

    private static Dictionary<string, object?> Success(Dictionary<string, object?> extra)
    {
        extra["success"] = true;
        return extra;
    }

    private static Dictionary<string, object?> Failure(string message) =>
        new() { ["success"] = false, ["message"] = message };
}
