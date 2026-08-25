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
    Task StartConnectionAsync(SwitchRoomRole role, string roomCode, CancellationToken cancellationToken = default);
    Task StopConnectionAsync(CancellationToken cancellationToken = default);
    Task ReleaseTradeRoomAsync(string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(CancellationToken cancellationToken = default);
    Task<string> CreateSupportBundleAsync(CancellationToken cancellationToken = default);
}

public sealed class ControlApiClient : IControlGateway
{
    public const string ApiBase = "http://127.0.0.1:8787";

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
            using var response = await _http.GetAsync("/api/status", probeTimeout.Token);
            if (!response.IsSuccessStatusCode) return null;
            var dto = await response.Content.ReadFromJsonAsync<StatusDto>(JsonOptions, probeTimeout.Token);
            return dto is null ? null : new ControlStatus(
                dto.Status ?? "ready", dto.Version ?? "unknown", dto.RunId ?? "",
                dto.EndpointProcessRunning, dto.RadioChecked, dto.TunnelConnected,
                dto.SessionId, dto.Error);
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
        SwitchRoomRole role, string roomCode, CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>(
            "/api/session/start", new
            {
                role = role == SwitchRoomRole.Creator ? "host" : "guest",
                passcode = roomCode,
            }, cancellationToken);

    public async Task StopConnectionAsync(CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>("/api/session/stop", new { }, cancellationToken);

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
            "/api/support-bundle", new { }, cancellationToken);
        return result.Path ?? "Support file created";
    }

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
