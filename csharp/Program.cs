using System.Runtime;
using System.Text;
using System.Text.Json;
using Microsoft.IdentityModel.JsonWebTokens;
using Microsoft.IdentityModel.Tokens;
using Npgsql;

const string Query = """
    SELECT id, status, total_cents, items,
      to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
      FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20
    """;

var secret = Environment.GetEnvironmentVariable("JWT_SECRET")
    ?? throw new InvalidOperationException("JWT_SECRET is not set");
var connectionString = Environment.GetEnvironmentVariable("DB_CONN")
    ?? throw new InvalidOperationException("DB_CONN is not set");
var port = Environment.GetEnvironmentVariable("PORT") ?? "8080";

// The server log keeps what .NET chose under the core pinning: its CPU count and garbage collector.
Console.WriteLine($".NET {Environment.Version}, ProcessorCount {Environment.ProcessorCount}, server GC {GCSettings.IsServerGC}");

var builder = WebApplication.CreateBuilder(args);
builder.Logging.SetMinimumLevel(LogLevel.Warning);
builder.Services.ConfigureHttpJsonOptions(o => o.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower);

await using var dataSource = NpgsqlDataSource.Create(connectionString);
var tokens = new JsonWebTokenHandler();
var validation = new TokenValidationParameters
{
    IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(secret)),
    ValidAlgorithms = [SecurityAlgorithms.HmacSha256],
    ValidateIssuer = false,
    ValidateAudience = false,
    RequireExpirationTime = true,
};

var app = builder.Build();

app.MapGet("/health", () => "ok");

app.MapGet("/customers/{id:int}/orders", async (int id, HttpRequest request) =>
{
    string? header = request.Headers.Authorization;
    if (header is null || !header.StartsWith("Bearer ", StringComparison.Ordinal))
    {
        return Results.Unauthorized();
    }
    var result = await tokens.ValidateTokenAsync(header[7..], validation);
    if (!result.IsValid || !HasScope(result.Claims, "orders:read"))
    {
        return Results.Unauthorized();
    }
    await using var command = dataSource.CreateCommand(Query);
    command.Parameters.Add(new NpgsqlParameter { Value = id });
    await using var reader = await command.ExecuteReaderAsync();
    var orders = new List<Order>(20);
    while (await reader.ReadAsync())
    {
        orders.Add(new Order(reader.GetInt32(0), reader.GetString(1), reader.GetInt32(2), reader.GetInt32(3), reader.GetString(4)));
    }
    return Results.Ok(new Reply(id, orders));
});

await app.RunAsync($"http://127.0.0.1:{port}");

static bool HasScope(IDictionary<string, object> claims, string wanted) =>
    claims.TryGetValue("scope", out var scope)
    && scope is string scopes
    && scopes.Split(' ', StringSplitOptions.RemoveEmptyEntries).Contains(wanted);

internal sealed record Order(int Id, string Status, int TotalCents, int Items, string CreatedAt);

internal sealed record Reply(int CustomerId, List<Order> Orders);
