# Close Out Remaining Post-OAuth Hardening Gaps

**Status:** ✅ Shipped — Part 1, Part 3, and Parts 4-6 all done and live-verified (Python +
.NET). Full test suites green on both stacks (463 Python, 268 .NET), zero regressions.

## Context

After the OAuth2/OIDC feature ([10-oauth-authorization.md](10-oauth-authorization.md), Phases
A-E) shipped and was live-verified, six open items remained, tracked in
`docs/security-guide.md`'s "Known Issues" and `docs/agent-audit-matrix.md`'s "Open items."
This plan covers items **1, 3, 4, 5, 6** (item 2, JWKS signing-key rotation, is explicitly out
of scope):

1. **.NET specialists + .NET MCP host aren't containerized** — no Dockerfile for any of the 5
   specialist projects or `ECommerceAgents.Mcp`; `docker-compose.dotnet.yml` already
   references the 5 specialist Dockerfile paths (they don't exist yet — a deliberate "Phase 0
   scaffold" per its own header comment) and has no MCP service at all.
3. **OAuth client registry is fixed/seeded, no dynamic registration** (RFC 7591) — every
   client comes from `scripts/seed.py`'s static list; no `/oauth/register`.
4. `review_sentiment/tools.py::draft_seller_response` — no role check.
5. `inventory_fulfillment/tools.py::place_backorder` / `calculate_fulfillment_plan` — no role
   check.
6. `order_management`/`shared/tools`::`cancel_order`, `modify_order`, `process_refund` — no
   role check (`process_refund` actually lives in `shared/tools/return_tools.py`, not
   `order_management/tools.py` — a naming discrepancy from the original audit note).

Three parallel codebase-exploration passes mapped the exact existing patterns each item must
match before this was written. Two decisions were locked with the user up front:

- **RBAC (4/5/6): full parity.** Guard the Python tools with the existing `@requires_role`
  decorator, **and** establish a new .NET tool-guard pattern (none exists today — only
  route-level 403 guards) so the 5 .NET-ported tools get the same protection.
  `process_refund` has no .NET port, so its guard is Python-only.
- **Dynamic registration (3): scoped initial-access-token**, not a static shared secret.
  Registration requires an AS-issued bearer token carrying a new `client:register` scope
  (obtained via `client_credentials` by a dedicated seeded admin client); the AS verifies it
  in-process against its own JWKS. Registered clients are capped to `client_credentials` grant
  only and to the two MCP read scopes (`mcp:product`, `mcp:inventory`) — never
  `agent:invoke`/`api:chat`/admin scopes. Off by default via a new
  `AUTH_ALLOW_DYNAMIC_REGISTRATION` flag.

---

## Part 1 — Containerize the .NET specialists + MCP host ✅ done

**Template**: `agents/dotnet/src/ECommerceAgents.Orchestrator/Dockerfile` — two-stage build
(`sdk:10.0` → `aspnet:10.0`), repo-root build context, copies `Directory.Packages.props` +
`ECommerceAgents.sln` + `src/` + `tests/`, `dotnet publish <csproj> -c Release -o /app/out`,
non-root `dotnet` system user (deliberately no explicit uid/gid — collides with the base
image's pre-baked `ubuntu` uid 1000), bakes `agents/python/config` alongside the binary so
`PromptLoader` finds prompts with no volume mount, `ASPNETCORE_URLS` + `EXPOSE` + hardcoded
`ENTRYPOINT ["dotnet", "<Project>.dll"]`. No `HEALTHCHECK` on this one, but new containers
in this repo get one.

**Steps**

1. Six new Dockerfiles, one per project, each mirroring the orchestrator template exactly
   except for the project name, port, and an added `HEALTHCHECK`:
   - `agents/dotnet/src/ECommerceAgents.ProductDiscovery/Dockerfile` (port 8081)
   - `agents/dotnet/src/ECommerceAgents.OrderManagement/Dockerfile` (port 8082)
   - `agents/dotnet/src/ECommerceAgents.PricingPromotions/Dockerfile` (port 8083)
   - `agents/dotnet/src/ECommerceAgents.ReviewSentiment/Dockerfile` (port 8084)
   - `agents/dotnet/src/ECommerceAgents.InventoryFulfillment/Dockerfile` (port 8085)
   - `agents/dotnet/src/ECommerceAgents.Mcp/Dockerfile` (port 9001 — see fix below)
   Add to the runtime stage, before `USER dotnet`:
   `RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*`
   then `HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 CMD curl -sf http://localhost:<port>/health || exit 1`
   (every specialist and the Mcp host already exposes `GET /health` via `AgentHost.cs` /
   `McpEndpoints.cs`).
2. Fix two small pre-existing bugs surfaced by exploration, both in the direct path of
   getting this stack to actually run correctly:
   - `AgentSettingsLoader.cs`'s `RedisUrl` reads only the `REDIS_URL` env var, but
     `docker-compose.dotnet.yml`'s `&agent-env` anchor supplies `ConnectionStrings__Redis`
     (double-underscore `IConfiguration` binding) — the value is silently never picked up.
     Fix by mirroring the existing `DatabaseUrl` pattern one line above it:
     `config.GetConnectionString("Redis") ?? Get("REDIS_URL", "redis://localhost:6379")`.
   - `ECommerceAgents.Mcp/Program.cs`'s bind-port fallback is hardcoded `9000`, but its own
     settings default audience/scope/resource-URL (`McpAudience="mcp-inventory"`,
     `McpResourceUrl="http://localhost:9001/mcp"`) all say `9001` — this host is the
     inventory MCP, not product. Change the fallback literal to `9001` for internal
     consistency.
3. Add an `mcp-inventory` service to `docker-compose.dotnet.yml`, modeled on the existing
   `orchestrator` service block and on the Python compose's `mcp-inventory` service (env-var
   names must match exactly across stacks): `build.dockerfile:
   agents/dotnet/src/ECommerceAgents.Mcp/Dockerfile`, `ports: ["9001:9001"]`,
   `ASPNETCORE_URLS: http://0.0.0.0:9001`, `MCP_AUTH_ENABLED`, `MCP_INVENTORY_AUDIENCE`,
   `MCP_INVENTORY_REQUIRED_SCOPE`, `MCP_INVENTORY_RESOURCE_URL`, `AUTH_SERVER_ISSUER`,
   `AUTH_SERVER_JWKS_URL`, `ConnectionStrings__Postgres`, `profiles: ["mcp"]`. No .NET
   equivalent of `mcp-product` exists or is being added here — a pre-existing, unaddressed
   asymmetry, noted explicitly in the docs update below.
4. No other compose changes needed — the 5 specialist service blocks already exist and
   already point at the right Dockerfile paths; they just needed the files to exist. Update
   the file's header comment (currently: "Phase 0 scaffolds only the compose structure ...
   this is expected") to reflect that the Dockerfiles now exist.
5. Docs: update `docs/security-guide.md`'s "Known Issues" bullet 2 and
   `docs/agent-audit-matrix.md`'s open item #4 to reflect this is done; note the still-open
   `mcp-product`-equivalent asymmetry explicitly.

**One correction during implementation**: `RedisUrl` has no actual .NET consumer yet (grepped —
no `IConnectionMultiplexer`/`StackExchange.Redis` usage anywhere in `agents/dotnet/src/`), so
the fix couldn't be verified behaviorally end-to-end against a real Redis-backed feature. It's
still a real, correct fix (mirrors `DatabaseUrl`'s already-working precedence exactly, and
future-proofs whenever Redis is actually wired in) — verified instead with a direct unit test:
new `AgentSettingsLoaderTests.cs` (2 tests) constructs an `IConfiguration` with
`ConnectionStrings:Redis` set and asserts `AgentSettingsLoader.Load` now picks it up, plus a
default-fallback case.

**Tests shipped**: `AgentSettingsLoaderTests.cs` (2 new, `ECommerceAgents.Shared.Tests`) for the
Redis fix above. No other new tests needed — the Dockerfiles/compose wiring have no code path
of their own to unit-test; their correctness is what the live verification below establishes.
Full .NET solution: 268 passed, 0 regressions.

**Verification**
- `dotnet build`/`dotnet test` — full suite green (268 passed), zero regressions.
- **✅ Live**: `docker compose -f docker-compose.dotnet.yml --profile agents --profile mcp --profile seed up --build`
  — all 8 services (db, redis, aspire, auth-server, orchestrator, 5 specialists, mcp-inventory)
  came up healthy on the first attempt, no build or wiring bugs found (unlike the Python MCP
  Docker work in Phase D, which hit three real infra bugs on first run — this went clean).
  Curled every specialist's `/health` and `/.well-known/agent-card.json` (all 200, correct
  shapes) plus `mcp-inventory`'s `/health`. Seeded the DB, logged in as a real seeded user
  (`alice.johnson@gmail.com`), and drove one real chat message ("Is the Sony WH-1000XM5 in
  stock?") through the real orchestrator with real Azure OpenAI credentials — orchestrator logs
  confirm it routed via `AGENT_REGISTRY` to `http://inventory-fulfillment:8085/message:send`,
  got a real 200 back, and the orchestrator returned a real DB-grounded answer (out-of-stock +
  actual restock date from the seeded `restock_schedule` table). Torn down cleanly afterward.

---

## Part 3 — Dynamic client registration (RFC 7591, gated) ✅ done

**What shipped, matching the plan almost exactly, with one real design correction found by
live-testing (below):**

- `shared/config.py` — `AUTH_SERVER_AUDIENCE: str = "ecommerce-auth-server"` (the AS's own
  resource identifier) and `AUTH_ALLOW_DYNAMIC_REGISTRATION: bool = False`.
- `auth_server/token.py::_scope_audience_map()` extended with
  `"client:register": settings.AUTH_SERVER_AUDIENCE`, and `auth_server/server.py`'s
  `scopes_supported` list (passed to authlib's `AuthorizationServer.__init__`) gained
  `"client:register"` too — without it, minting a `client:register` token itself fails
  `invalid_scope` (caught by the live round-trip test, not the unit tests, since the unit
  tests construct the server the same way production does and so shared the same gap until
  fixed once, here).
- `scripts/seed.py`'s `OAUTH_CLIENTS` gained a dedicated `auth-admin` client
  (`client_credentials` only, scope `client:register`, audience `ecommerce-auth-server`) —
  kept separate from `orchestrator` so the broadly-scoped end-user-facing client isn't also
  the one trusted to mint new OAuth clients.
- New `auth_server/register.py`: `REGISTRABLE_SCOPES` (the two MCP read scopes only),
  `RegistrationError`, `validate_registration_request` (client_name required; scope required
  and must be a subset of `REGISTRABLE_SCOPES`; `grant_types` if present must be exactly
  `["client_credentials"]`; `redirect_uris` rejected outright — no redirect flow exists on
  this AS), `create_client` (generates `ext-<16 hex>` client id + a `generate_token(48)`
  secret, hashes via `hash_password`, derives audiences from the same `_scope_audience_map()`
  token issuance uses, INSERTs into `oauth_clients`).
- `auth_server/main.py`: `POST /oauth/register` route, `registration_endpoint` field added to
  the RFC 8414 `metadata()` response, 403 when the flag is off, RFC 7591-shaped 201 response
  on success (`client_secret_expires_at: 0` — never expires), reloading `_server.client_store`
  after every successful registration so the new client is immediately usable.

**A real bug found only by live-testing this against the actual running auth-server, not by
unit tests alone — the same pattern as every other phase's live-verification findings:** the
first implementation verified the registration bearer token by reusing
`shared/oauth/verifier.py::RS256Verifier` — the JWKS-over-HTTP verifier every *other* resource
server in this codebase correctly uses. Live curl testing against the actual container
deadlocked every time (`PyJWKClientConnectionError: ... timed out`): the AS is a
single-worker asyncio process, and its own `/oauth/register` handler synchronously fetching
its own `/.well-known/jwks.json` over HTTP blocks the very same event loop that would need to
accept and service that inbound self-directed connection — it can never complete, so it times
out. No other resource server hits this because none of them is handling a request *from
itself* while its verifier fetches JWKS from the AS's *separate* process. **Fixed by
verifying entirely in-process instead**: `auth_server/main.py` now keeps the AS's own
in-memory signing key in a module-level `_signing_key` (set once in `lifespan()`, alongside
`_server`), and `_verify_registration_token()` calls `joserfc_jwt.decode(token, _signing_key)`
directly — no network round trip — followed by manual `iss`/`aud`/`scope`/`exp` claim checks
(`joserfc`'s `decode` only verifies the signature; unlike PyJWT's `jwt.decode` it does not
validate claims itself). `RS256Verifier` and its import were removed from `main.py` entirely
rather than left as dead code.

**Tests shipped**: `agents/python/tests/test_auth_server_registration.py` (7 new) — following
`test_auth_server_integration.py`'s `clean_db` + real `OAuthAuthorizationServer` pattern,
driven over HTTP via `httpx.AsyncClient(transport=ASGITransport(app=app))` with the app's
`lifespan` bypassed the same way the other auth-server integration tests already do (module
globals `main._server`/`main._signing_key` set directly via monkeypatch instead — no JWKS
stub needed at all now that verification is in-process): disabled-by-default → 403; missing
token → 401 + `WWW-Authenticate`; wrong-scope real token → 401; valid registration → 201, the
returned secret verifies via `bcrypt.checkpw` against the stored hash, and the new client
immediately completes a real `client_credentials` grant for its registered scope (full round
trip, not just an INSERT assertion); non-registrable scope requested → 400
`invalid_client_metadata`; missing `client_name` → 400; disallowed `grant_types` → 400. Full
suite: 463 passed (441 baseline + 15 RBAC tool-guard tests + 7 registration tests), 2
pre-existing unrelated failures untouched (no `OPENAI_API_KEY` in this shell).

**Docs**: `docs/security-guide.md`'s Known Issues rewritten to describe the shipped,
gated, scope-limited flow (including the in-process-verification gotcha above);
`docs/mcp-integration.md` gained a "Getting credentials as a third-party MCP client" section.

**Done when**
- `AUTH_ALLOW_DYNAMIC_REGISTRATION=true`, gated registration works end to end; flag off (the
  default) → `POST /oauth/register` is a 403, byte-for-byte unaffected otherwise.
  **✅ Verified live against a real running auth-server + mcp-product container**: acquired a
  real `client:register` token as the seeded `auth-admin` client, registered a brand-new
  client via `curl`, and used its returned credentials to acquire a real `mcp:product` token
  that successfully completed the MCP `initialize` handshake against the real live
  `mcp-product` server — full external-client round trip, not just unit tests.

---

## Parts 4-6 — RBAC guards on the six tools (Python + .NET parity)

**Existing pattern (Python)**: `shared/guardrails/roles.py::requires_role(*roles)` —
decorator under `@tool`, reads the `current_user_role` ContextVar, admin always allowed,
gated by `settings.GUARDRAILS_ENABLED` (on by default), returns a `permission_denied` dict on
denial. Already applied to 4 tools in `shared/tools/seller_tools.py`.

**Existing pattern (.NET)**: none at the tool layer — only route-level `RequireSeller()`/
`RequireAdmin()` 403 guards in `SellerRoutes.cs`/`AdminRoutes.cs`. Every target tool's result
type (`CancelOrderResult`, `ModifyOrderResult`, `FulfillmentPlanResult`,
`PlaceBackorderResult`, `SellerResponseResult`) already follows one uniform convention: a
static `Failure(string message)` factory setting an `Error` field. The new guard reuses that
shape.

**Steps**

1. Python — six `@requires_role` additions, decorator placed directly under `@tool(...)`:
   - `review_sentiment/tools.py:450` `draft_seller_response` -> `@requires_role("seller", "admin")`
   - `inventory_fulfillment/tools.py:222` `calculate_fulfillment_plan` -> `@requires_role("seller", "admin")`
   - `inventory_fulfillment/tools.py:316` `place_backorder` -> `@requires_role("seller", "admin")`
   - `order_management/tools.py:224` `cancel_order` -> `@requires_role("customer", "seller", "admin")`
   - `order_management/tools.py:289` `modify_order` -> `@requires_role("customer", "seller", "admin")`
   - `shared/tools/return_tools.py:179` `process_refund` -> `@requires_role("customer", "seller", "admin")`
2. .NET — new `RoleGuard` helper, `ECommerceAgents.Shared/Guardrails/RoleGuard.cs`:
   ```csharp
   public static class RoleGuard
   {
       public static string? Ensure(AgentSettings settings, params string[] roles)
       {
           if (!settings.GuardrailsEnabled) return null;
           var allowed = new HashSet<string>(roles, StringComparer.OrdinalIgnoreCase) { "admin" };
           var role = RequestContext.CurrentUserRole ?? "";
           if (allowed.Contains(role)) return null;
           return $"You don't have permission to perform this action. It requires one of these roles: {string.Join(", ", allowed.OrderBy(r => r, StringComparer.Ordinal))}.";
       }
   }
   ```
3. New `GuardrailsEnabled` setting: `AgentSettings.cs` (default `true`) and
   `AgentSettingsLoader.cs` (env `GUARDRAILS_ENABLED` — same var name as Python).
4. .NET — five call sites, each tool class gets `AgentSettings settings` added as a second
   constructor parameter (DI already has it registered as a singleton), and the guard as the
   tool method's first line:
   - `OrderTools` -> `CancelOrder`, `ModifyOrder`: `"customer", "seller"` (+ admin always).
   - `InventoryTools` -> `CalculateFulfillmentPlan`, `PlaceBackorder`: `"seller", "admin"`.
   - `ReviewTools` -> `DraftSellerResponse`: `"seller", "admin"`.
   - No .NET change for `process_refund` — no .NET port exists.

**Tests**
- Python: extend `tests/test_guardrails_roles.py`'s pattern for the six newly-guarded tools
  (disallowed role denied, allowed role passes through, admin always allowed,
  `GUARDRAILS_ENABLED=False` bypasses).
- .NET: new `RoleGuardTests.cs` in `ECommerceAgents.Shared.Tests` (allow/deny/admin-always/
  disabled), plus per-tool tests in `OrderManagement.Tests`/`InventoryFulfillment.Tests`/
  `ReviewSentiment.Tests`.

**What shipped, matching the plan exactly**: Python decorator + .NET `RoleGuard` on all 5
shared tools, `GuardrailsEnabled` setting added to .NET, all 5 .NET call sites wired with the
guard as the first line, existing per-tool test fixtures updated to set an allowed role
(`OrderToolsTests`→customer, `InventoryToolsTests`→seller, `ReviewToolsTests`→seller) since
none previously set `RequestContext.CurrentUserRole` at all.

**Tests shipped**: Python — `tests/test_tool_role_guards.py` (15 new): denied/allowed for
each of the 6 tools, admin-always-allowed, one disabled-bypass case; denial cases need no DB
at all (the guard runs before any `get_pool()` call in every one of these functions), allowed
cases prove pass-through without needing full seed fixtures (empty-list/no-context/not-found
short circuits). .NET — `RoleGuardTests.cs` (6 new, `ECommerceAgents.Shared.Tests`:
allow/admin-always/deny/deny-missing-role/disabled/case-insensitive) plus one denial `[Fact]`
added to each of `OrderToolsTests`, `InventoryToolsTests` (×2), `ReviewToolsTests` — 10 new
.NET tests total.

**Docs**: `docs/agent-audit-matrix.md`'s open items 1-3 closed (Role Enforce flipped to
`Done` for order-management/review-sentiment/inventory-fulfillment in both the per-agent
tables and the summary table); open items list renumbered to the two genuinely-still-open,
non-blocking notes (pricing-promotions forward-looking note, .NET `mcp-product` asymmetry).

---

## Verification (all parts) — ✅ all done

- Python: `uv run ruff check .`/`ruff format --check .` — zero new issues (verified by diffing
  against pre-existing debt: the repo already has 145 lint findings and 36 files with format
  debt entirely unrelated to this work, confirmed via `git stash`/`ruff format --diff` showing
  none of it touches lines this session added). `uv run pytest`: **463 passed**, 2
  pre-existing unrelated failures untouched (no `OPENAI_API_KEY` in this shell — same two
  failures present before this session started).
- .NET: `dotnet build` clean, `dotnet test`: **268 passed**, 0 failed, 0 regressions.
- **Live, Part 1** ✅: full `docker-compose.dotnet.yml` stack (8 services) up healthy on the
  first attempt; real chat round trip through the .NET orchestrator (real Azure OpenAI, real
  login) correctly routed via `AGENT_REGISTRY` to a real specialist and back with a real
  DB-grounded answer.
- **Live, Part 3** ✅: with `AUTH_ALLOW_DYNAMIC_REGISTRATION=true` against a real running
  auth-server + mcp-product container, acquired a real `auth-admin` `client:register` token,
  registered a brand-new client via curl, and used its returned credentials to acquire a real
  `mcp:product` token that successfully completed the MCP `initialize` handshake against the
  real live `mcp-product` server.
- **Live, Parts 4-6** ✅: rather than relying on LLM tool-selection non-determinism through
  the full chat path, verified directly against the actual shipped Docker images via `docker
  exec` (same code, same real Postgres, real structured logs) — `inventory-fulfillment`'s
  `place_backorder`: `customer` → real `permission_denied` (with the real
  `guardrails.role_denied` log line), `seller`/`admin` → guard passes, reaches real DB lookup;
  `order-management`'s `cancel_order`: `guest` → denied, `customer` → guard passes, reaches
  real DB lookup. Matches the unit-test-level proof (15 Python + 10 .NET tests, all against
  real Postgres, no mocks) with an additional check against the actual built artifact.
