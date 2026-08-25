using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using SwitchTrade.Desktop.Models;

namespace SwitchTrade.Desktop.Services;

public sealed class UserFacingException(string userMessage, string? technicalCode = null)
    : Exception(userMessage)
{
    public string UserMessage { get; } = userMessage;
    public string? TechnicalCode { get; } = technicalCode;
}

public interface IControlGateway : IDisposable
{
    Task<ControlStatus?> TryGetStatusAsync(CancellationToken cancellationToken = default);
    Task<TradeRoomInfo> CreateTradeRoomAsync(TradeRoomCreateRequest request, CancellationToken cancellationToken = default);
    Task<TradeRoomInfo> JoinTradeRoomAsync(string roomCode, CancellationToken cancellationToken = default);
    Task StartConnectionAsync(SwitchRoomRole role, RoomMembershipRole membershipRole,
        string roomCode, CancellationToken cancellationToken = default);
    Task StopConnectionAsync(CancellationToken cancellationToken = default);
    Task ReleaseTradeRoomAsync(string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(CancellationToken cancellationToken = default);
    Task<LivePartyProjection?> TryGetPartiesAsync(CancellationToken cancellationToken = default);
    Task RepairAdapterAsync(CancellationToken cancellationToken = default);
    Task<string> CreateSupportBundleAsync(CancellationToken cancellationToken = default);
}

public sealed class ControlApiClient : IControlGateway
{
    public const string ApiBase = "http://127.0.0.1:8787";
    public const string ReadinessContract = "app-readiness.v1";
    private const string CompatibleProductPrefix = "0.2.";

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNameCaseInsensitive = true,
    };

    private readonly HttpClient _http;

    public ControlApiClient(HttpMessageHandler? handler = null)
    {
        _http = handler is null ? new HttpClient() : new HttpClient(handler, disposeHandler: true);
        _http.BaseAddress = new Uri(ApiBase);
        _http.Timeout = TimeSpan.FromSeconds(4);
    }

    public async Task<ControlStatus?> TryGetStatusAsync(CancellationToken cancellationToken = default)
    {
        using var probeTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        probeTimeout.CancelAfter(TimeSpan.FromMilliseconds(500));
        try
        {
            using var response = await _http.GetAsync("/api/v1/app/readiness", probeTimeout.Token);
            if (!response.IsSuccessStatusCode) return null;
            var dto = await response.Content.ReadFromJsonAsync<ReadinessDto>(JsonOptions, probeTimeout.Token);
            if (dto is null) return null;
            var states = (dto.States ?? new Dictionary<string, ReadinessAxisDto>())
                .ToDictionary(
                    item => item.Key,
                    item => new ReadinessAxis(
                        item.Value.Status ?? "unknown",
                        item.Value.UserMessage ?? "Not checked",
                        item.Value.TechnicalCode ?? $"{item.Key}.unknown",
                        item.Value.PrimaryAction),
                    StringComparer.OrdinalIgnoreCase);
            var session = states.TryGetValue("session", out var sessionAxis)
                ? sessionAxis.TechnicalCode.Replace("session.", "", StringComparison.OrdinalIgnoreCase)
                : "idle";
            var compatible = dto.Compatible && dto.ContractVersion == ReadinessContract &&
                             (dto.ProductVersion?.StartsWith(CompatibleProductPrefix, StringComparison.Ordinal) ?? false);
            return new ControlStatus(
                session, dto.ProductVersion ?? "unknown", dto.RunId ?? "",
                dto.EndpointProcessRunning,
                states.TryGetValue("radio", out var radio) && radio.Status == "ready",
                states.TryGetValue("relay", out var relay) && relay.Status == "ready",
                dto.SessionId, dto.Failure?.Message,
                dto.ContractVersion ?? "unknown", compatible, states,
                dto.Failure?.Stage, dto.Failure?.PrimaryAction);
        }
        catch (HttpRequestException) { return null; }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { return null; }
        catch (JsonException) { return null; }
        catch (NotSupportedException) { return null; }
    }

    public async Task<TradeRoomInfo> CreateTradeRoomAsync(
        TradeRoomCreateRequest request, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<GroupResponse>(
            "/api/groups", new
            {
                name = request.RoomName,
                visibility = "private",
                trainer_display_name = request.TrainerDisplayName,
                game = request.Game.ToString(),
                language = request.Language.ToString(),
                offering = request.Offering,
                wanted = request.Wanted,
                note = request.Note,
            }, cancellationToken);
        return ToTradeRoom(result);
    }

    public async Task<TradeRoomInfo> JoinTradeRoomAsync(
        string roomCode, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<GroupResponse>(
            "/api/groups/join", new { passcode = roomCode }, cancellationToken);
        return ToTradeRoom(result);
    }

    public async Task StartConnectionAsync(
        SwitchRoomRole role, RoomMembershipRole membershipRole,
        string roomCode, CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>(
            "/api/v1/session/start", new
            {
                tunnel_seat = membershipRole == RoomMembershipRole.Owner ? "member_a" : "member_b",
                switch_room_role = role == SwitchRoomRole.Creator ? "creator" : "finder",
                passcode = roomCode,
            }, cancellationToken);

    public async Task StopConnectionAsync(CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>("/api/v1/session/stop", new { }, cancellationToken);

    public async Task ReleaseTradeRoomAsync(
        string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default)
    {
        var path = role == RoomMembershipRole.Owner
            ? $"/api/groups/{Uri.EscapeDataString(roomCode)}"
            : $"/api/groups/{Uri.EscapeDataString(roomCode)}/members/me";
        try
        {
            using var response = await _http.DeleteAsync(path, cancellationToken);
            await EnsureSuccess(response, cancellationToken);
        }
        catch (HttpRequestException)
        {
            throw new UserFacingException("SwitchTrade’s local service is not available.", "local_service_unavailable");
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new UserFacingException("SwitchTrade took too long to respond. Try again.", "request_timeout");
        }
    }

    public async Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.GetAsync("/api/hardware/profiles", cancellationToken);
            await EnsureSuccess(response, cancellationToken);
            var result = await response.Content.ReadFromJsonAsync<ProfilesResponse>(JsonOptions, cancellationToken);
            return (result?.Profiles ?? []).Select(profile =>
            {
                var friendly = profile.UsbId?.ToLowerInvariant() switch
                {
                    "0bda:818b" => "Realtek RTL8192EU",
                    "0bda:8179" => "Realtek RTL8188EU",
                    _ => "USB Wi-Fi adapter",
                };
                var supported = profile.Status == "beta-candidate";
                var label = profile.Status switch
                {
                    "beta-candidate" => "Beta candidate",
                    "quarantined" => "Test-only adapter",
                    _ => "Needs review",
                };
                return new AdapterProfileViewData(
                    friendly, label,
                    supported ? "Available for the current beta workflow; two-adapter certification is pending."
                              : "Not selected automatically for trading.",
                    $"USB {profile.UsbId?.ToUpperInvariant()} · {string.Join(", ", profile.Roles ?? [])}",
                    supported);
            }).ToArray();
        }
        catch (HttpRequestException)
        {
            throw new UserFacingException("SwitchTrade’s local service is not available.", "local_service_unavailable");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new UserFacingException("SwitchTrade took too long to respond. Try again.", "request_timeout");
        }
        catch (JsonException)
        {
            throw new UserFacingException("SwitchTrade received an incomplete response.", "invalid_response");
        }
        catch (NotSupportedException)
        {
            throw new UserFacingException("SwitchTrade received an incompatible response.", "invalid_response");
        }
    }

    public async Task<string> CreateSupportBundleAsync(CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<SupportBundleResponse>(
            "/api/v1/support-bundle", new { }, cancellationToken);
        return result.Path ?? "Support file created";
    }

    public async Task RepairAdapterAsync(CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>(
            "/api/v1/app/repair", new { action = "recheck_adapter" }, cancellationToken);

    public async Task<LivePartyProjection?> TryGetPartiesAsync(
        CancellationToken cancellationToken = default)
    {
        using var probeTimeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        probeTimeout.CancelAfter(TimeSpan.FromMilliseconds(650));
        try
        {
            using var response = await _http.GetAsync("/api/v1/trade-room/parties", probeTimeout.Token);
            if (!response.IsSuccessStatusCode) return null;
            using var document = await JsonDocument.ParseAsync(
                await response.Content.ReadAsStreamAsync(probeTimeout.Token),
                cancellationToken: probeTimeout.Token);
            var root = document.RootElement;
            var status = Text(root, "observer_status") ?? "unavailable";
            var confirmed = root.TryGetProperty("trading_room_confirmed", out var confirmedValue) &&
                            confirmedValue.ValueKind == JsonValueKind.True;
            var commits = ParseCommits(root);
            if (!root.TryGetProperty("parties", out var parties))
                return new(null, null, status, confirmed, commits);
            return new(
                ParseParty(parties, "member_a", "Member A", "Blue"),
                ParseParty(parties, "member_b", "Member B", "Teal"),
                status, confirmed, commits);
        }
        catch (HttpRequestException) { return null; }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { return null; }
        catch (JsonException) { return null; }
    }

    private static PartyPreviewViewData? ParseParty(
        JsonElement parties, string seat, string heading, string accent)
    {
        if (!parties.TryGetProperty(seat, out var party) ||
            Text(party, "status") != "available" ||
            !party.TryGetProperty("snapshot", out var snapshot) ||
            snapshot.ValueKind != JsonValueKind.Object ||
            !snapshot.TryGetProperty("slots", out var slots)) return null;
        var result = new List<PokemonPreviewViewData>();
        foreach (var slot in slots.EnumerateArray())
        {
            var occupied = slot.TryGetProperty("occupied", out var occupiedValue) &&
                           occupiedValue.ValueKind == JsonValueKind.True;
            if (!occupied)
            {
                result.Add(new("", "", 0, "", null, null, null, null, [], null, true, true));
                continue;
            }
            var stats = Object(slot, "stats");
            var ivs = Object(slot, "ivs");
            var evs = Object(slot, "evs");
            var moves = new List<MovePreview>();
            if (slot.TryGetProperty("moves", out var moveValues))
            {
                foreach (var move in moveValues.EnumerateArray())
                {
                    var name = FieldText(move, "name");
                    var id = FieldInt(move, "move_id");
                    if (!string.IsNullOrWhiteSpace(name)) moves.Add(new(name));
                    else if (id is > 0) moves.Add(new($"Move #{id}"));
                }
            }
            var trainer = Object(slot, "trainer");
            result.Add(new(
                FieldText(slot, "nickname") ?? "Unknown",
                FieldText(slot, "species") ?? "Unknown",
                FieldInt(slot, "level") ?? 0,
                FieldText(slot, "nature") ?? "Unavailable",
                ItemLabel(FieldInt(slot, "held_item")),
                new BattleStats(
                    FieldInt(slot, "current_hp") ?? 0,
                    FieldInt(stats, "attack") ?? 0,
                    FieldInt(stats, "defense") ?? 0,
                    FieldInt(stats, "sp_attack") ?? 0,
                    FieldInt(stats, "sp_defense") ?? 0,
                    FieldInt(stats, "speed") ?? 0),
                Six(ivs), Six(evs), moves,
                new TrainerPreview(
                    FieldText(trainer, "name") ?? "Unknown",
                    FieldInt(trainer, "trainer_id"),
                    Language(FieldInt(trainer, "language"))),
                IsLive: true));
        }
        while (result.Count < 6)
            result.Add(new("", "", 0, "", null, null, null, null, [], null, true, true));
        return new(heading, accent, result.Take(6).ToArray());
    }

    private static List<TradeCommitProjection> ParseCommits(JsonElement root)
    {
        if (!root.TryGetProperty("commits", out var values) ||
            values.ValueKind != JsonValueKind.Array) return [];
        var result = new List<TradeCommitProjection>();
        foreach (var value in values.EnumerateArray())
        {
            var id = Text(value, "commit_id");
            if (string.IsNullOrWhiteSpace(id)) continue;
            var index = value.TryGetProperty("trade_index", out var indexValue) &&
                        indexValue.TryGetInt32(out var number) ? number : 0;
            DateTimeOffset? committedAt = DateTimeOffset.TryParse(
                Text(value, "committed_at"), out var parsed) ? parsed : null;
            result.Add(new(id, index, Text(value, "outcome") ?? "committed", committedAt));
        }
        return result;
    }

    private static JsonElement Object(JsonElement parent, string name) =>
        parent.TryGetProperty(name, out var value) && value.ValueKind == JsonValueKind.Object
            ? value : default;
    private static string? Text(JsonElement parent, string name) =>
        parent.ValueKind == JsonValueKind.Object && parent.TryGetProperty(name, out var value) &&
        value.ValueKind == JsonValueKind.String ? value.GetString() : null;
    private static string? FieldText(JsonElement parent, string name)
    {
        var field = Object(parent, name);
        return Text(field, "value");
    }
    private static int? FieldInt(JsonElement parent, string name)
    {
        var field = Object(parent, name);
        return field.ValueKind == JsonValueKind.Object && field.TryGetProperty("value", out var value) &&
               value.TryGetInt32(out var number) ? number : null;
    }
    private static SixValues Six(JsonElement value) => new(
        FieldInt(value, "hp") ?? 0, FieldInt(value, "attack") ?? 0,
        FieldInt(value, "defense") ?? 0, FieldInt(value, "sp_attack") ?? 0,
        FieldInt(value, "sp_defense") ?? 0, FieldInt(value, "speed") ?? 0);
    private static string? ItemLabel(int? id) => id is null or 0 ? null : $"Item #{id}";
    private static GameLanguage Language(int? id) => id switch
    {
        1 => GameLanguage.Japanese,
        2 => GameLanguage.English,
        3 => GameLanguage.French,
        4 => GameLanguage.Italian,
        5 => GameLanguage.German,
        7 => GameLanguage.Spanish,
        _ => GameLanguage.None,
    };

    private async Task<T> PostAsync<T>(string path, object body, CancellationToken cancellationToken)
    {
        try
        {
            using var response = await _http.PostAsJsonAsync(path, body, cancellationToken);
            await EnsureSuccess(response, cancellationToken);
            var value = await response.Content.ReadFromJsonAsync<T>(JsonOptions, cancellationToken);
            return value ?? throw new UserFacingException(
                "SwitchTrade received an incomplete response.", "invalid_response");
        }
        catch (HttpRequestException)
        {
            throw new UserFacingException(
                "SwitchTrade’s local service is not available.", "local_service_unavailable");
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new UserFacingException(
                "SwitchTrade took too long to respond. Try again.", "request_timeout");
        }
        catch (JsonException)
        {
            throw new UserFacingException(
                "SwitchTrade received an incomplete response.", "invalid_response");
        }
        catch (NotSupportedException)
        {
            throw new UserFacingException(
                "SwitchTrade received an incompatible response.", "invalid_response");
        }
    }

    private static async Task EnsureSuccess(HttpResponseMessage response, CancellationToken cancellationToken)
    {
        if (response.IsSuccessStatusCode) return;
        string? detail = null;
        try
        {
            var problem = await response.Content.ReadFromJsonAsync<ProblemDto>(JsonOptions, cancellationToken);
            detail = problem?.Detail;
        }
        catch (JsonException) { }
        catch (NotSupportedException) { }

        var message = response.StatusCode switch
        {
            HttpStatusCode.NotFound => "We couldn’t find that Trade Room. Check the code and try again.",
            HttpStatusCode.Conflict => "This Trade Room already has two players or is already in use.",
            HttpStatusCode.ServiceUnavailable => "Online rooms are temporarily unavailable.",
            HttpStatusCode.BadRequest => "SwitchTrade can’t start this connection yet. Check the room and adapter.",
            _ => "SwitchTrade couldn’t complete that action. Try again.",
        };
        throw new UserFacingException(message, detail);
    }

    private static TradeRoomInfo ToTradeRoom(GroupResponse result) => new(
        result.Group?.Name ?? "Private Trade Room",
        result.Group?.Passcode ?? "",
        result.Group?.Visibility ?? "private",
        result.Group?.Participants ?? 1,
        result.Scope ?? "local_demo",
        result.Group?.TrainerDisplayName ?? "",
        ParseGame(result.Group?.Game),
        ParseLanguage(result.Group?.Language),
        result.Group?.Offering ?? "",
        result.Group?.Wanted ?? "",
        result.Group?.Note ?? "");

    private static GameVersionChoice ParseGame(string? value) =>
        Enum.TryParse<GameVersionChoice>(value, ignoreCase: true, out var parsed) ? parsed : GameVersionChoice.None;

    private static GameLanguage ParseLanguage(string? value) =>
        Enum.TryParse<GameLanguage>(value, ignoreCase: true, out var parsed) ? parsed : GameLanguage.None;

    public void Dispose() => _http.Dispose();

    private sealed record StatusDto(
        string? Status,
        string? Version,
        [property: JsonPropertyName("run_id")] string? RunId,
        [property: JsonPropertyName("endpoint_process_running")] bool EndpointProcessRunning,
        [property: JsonPropertyName("radio_checked")] bool RadioChecked,
        [property: JsonPropertyName("tunnel_connected")] bool TunnelConnected,
        [property: JsonPropertyName("session_id")] string? SessionId,
        string? Error);

    private sealed record ReadinessDto(
        [property: JsonPropertyName("contract_version")] string? ContractVersion,
        [property: JsonPropertyName("product_version")] string? ProductVersion,
        bool Compatible,
        [property: JsonPropertyName("run_id")] string? RunId,
        [property: JsonPropertyName("endpoint_process_running")] bool EndpointProcessRunning,
        [property: JsonPropertyName("session_id")] string? SessionId,
        IReadOnlyDictionary<string, ReadinessAxisDto>? States,
        FailureDto? Failure);
    private sealed record ReadinessAxisDto(
        string? Status,
        [property: JsonPropertyName("user_message")] string? UserMessage,
        [property: JsonPropertyName("technical_code")] string? TechnicalCode,
        [property: JsonPropertyName("primary_action")] string? PrimaryAction);
    private sealed record FailureDto(
        string? Stage,
        string? Code,
        string? Message,
        bool Recoverable,
        [property: JsonPropertyName("primary_action")] string? PrimaryAction);

    private sealed record GroupResponse(string? Scope, GroupDto? Group);
    private sealed record GroupDto(
        string? Name,
        string? Passcode,
        string? Visibility,
        int Participants,
        [property: JsonPropertyName("trainer_display_name")] string? TrainerDisplayName,
        string? Game,
        string? Language,
        string? Offering,
        string? Wanted,
        string? Note);
    private sealed record ProfilesResponse(IReadOnlyList<ProfileDto>? Profiles);
    private sealed record ProfileDto(
        [property: JsonPropertyName("usb_id")] string? UsbId,
        string? Status,
        IReadOnlyList<string>? Roles);
    private sealed record SupportBundleResponse(string? Path);
    private sealed record ProblemDto(string? Detail);
}
