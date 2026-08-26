using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using SwitchTrade.Desktop.Models;

namespace SwitchTrade.Desktop.Services;

public sealed class UserFacingException(string userMessage, string? technicalCode = null,
    string? stage = null, bool recoverable = false, string? primaryAction = null,
    string? correlationId = null)
    : Exception(userMessage)
{
    public string UserMessage { get; } = userMessage;
    public string? TechnicalCode { get; } = technicalCode;
    public string? Stage { get; } = stage;
    public bool Recoverable { get; } = recoverable;
    public string? PrimaryAction { get; } = primaryAction;
    public string? CorrelationId { get; } = correlationId;
}

public interface IControlGateway : IDisposable
{
    Task<ControlStatus?> TryGetStatusAsync(CancellationToken cancellationToken = default);
    Task<TradeRoomInfo> CreateTradeRoomAsync(TradeRoomCreateRequest request, CancellationToken cancellationToken = default);
    Task<TradeRoomInfo> JoinTradeRoomAsync(string roomCode, CancellationToken cancellationToken = default);
    Task<IReadOnlyList<PublicRoomListing>> GetPublicRoomsAsync(
        PublicRoomQuery query, CancellationToken cancellationToken = default);
    Task<TradeRoomInfo> JoinPublicRoomAsync(
        string listingId, string trainerDisplayName, CancellationToken cancellationToken = default);
    Task<AuthoritativeRoomProjection?> TryGetTradeRoomAsync(CancellationToken cancellationToken = default);
    Task StartConnectionAsync(SwitchRoomRole role, RoomMembershipRole membershipRole,
        string roomCode, CancellationToken cancellationToken = default);
    Task StopConnectionAsync(CancellationToken cancellationToken = default);
    Task ReleaseTradeRoomAsync(string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default);
    Task AbandonLocalAuthorityAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(CancellationToken cancellationToken = default);
    Task<IReadOnlyList<HardwareDeviceViewData>> GetHardwareDevicesAsync(CancellationToken cancellationToken = default);
    Task SelectHardwareDeviceAsync(
        string usbId, string instanceId, string busId, CancellationToken cancellationToken = default);
    Task<HardwareDiagnosticViewData> RunHardwareDiagnosticsAsync(
        string usbId, CancellationToken cancellationToken = default);
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
    private readonly string? _expectedReleaseId;

    public ControlApiClient(HttpMessageHandler? handler = null, string? expectedReleaseId = null)
    {
        _http = handler is null ? new HttpClient() : new HttpClient(handler, disposeHandler: true);
        _http.BaseAddress = new Uri(ApiBase);
        _http.Timeout = TimeSpan.FromSeconds(30);
        _expectedReleaseId = expectedReleaseId ?? InstalledReleaseId();
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
                             (dto.ProductVersion?.StartsWith(CompatibleProductPrefix, StringComparison.Ordinal) ?? false) &&
                             _expectedReleaseId is not null && dto.ReleaseId == _expectedReleaseId;
            return new ControlStatus(
                session, dto.ProductVersion ?? "unknown", dto.RunId ?? "",
                dto.EndpointProcessRunning,
                states.TryGetValue("radio", out var radio) && radio.Status == "ready",
                states.TryGetValue("relay", out var relay) && relay.Status == "ready",
                dto.SessionId, dto.Failure?.Message,
                dto.ContractVersion ?? "unknown", compatible, states,
                dto.Failure?.Stage, dto.Failure?.PrimaryAction, dto.Capabilities ?? [], dto.ReleaseId);
        }
        catch (HttpRequestException) { return null; }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { return null; }
        catch (JsonException) { return null; }
        catch (NotSupportedException) { return null; }
    }

    private static string? InstalledReleaseId()
    {
        try
        {
            var manifest = Path.Combine(AppContext.BaseDirectory, "manifest.json");
            var marker = Path.Combine(AppContext.BaseDirectory, ".switchtrade-release.json");
            using var document = JsonDocument.Parse(File.ReadAllBytes(manifest));
            using var markerDocument = JsonDocument.Parse(File.ReadAllBytes(marker));
            var root = document.RootElement;
            var markerRoot = markerDocument.RootElement;
            if (!root.TryGetProperty("schema", out var schema) || schema.GetInt32() != 2 ||
                !root.TryGetProperty("release_id", out var release) ||
                !markerRoot.TryGetProperty("schema", out var markerSchema) || markerSchema.GetInt32() != 1 ||
                !markerRoot.TryGetProperty("release_id", out var markerRelease)) return null;
            var value = release.GetString();
            return value is not null && markerRelease.GetString() == value &&
                   Regex.IsMatch(value, "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
                ? value : null;
        }
        catch (IOException) { return null; }
        catch (UnauthorizedAccessException) { return null; }
        catch (JsonException) { return null; }
        catch (InvalidOperationException) { return null; }
    }

    public async Task<TradeRoomInfo> CreateTradeRoomAsync(
        TradeRoomCreateRequest request, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<RoomResponse>(
            "/api/v1/trade-room", new
            {
                name = request.RoomName,
                visibility = request.Visibility == TradeRoomVisibility.Public ? "public" : "private",
                trainer_display_name = request.TrainerDisplayName,
                game = request.Game.ToString(),
                language = request.Language.ToString(),
                offering = request.Offering,
                wanted = request.Wanted,
                note = request.Note,
            }, cancellationToken);
        return ToTradeRoom(result.Room, request.Offering, request.Wanted, request.Note);
    }

    public async Task<TradeRoomInfo> JoinTradeRoomAsync(
        string roomCode, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<RoomResponse>(
            "/api/v1/trade-room/join", new { passcode = roomCode, trainer_display_name = "Trainer" },
            cancellationToken);
        return ToTradeRoom(result.Room);
    }

    public async Task<IReadOnlyList<PublicRoomListing>> GetPublicRoomsAsync(
        PublicRoomQuery query, CancellationToken cancellationToken = default)
    {
        var parameters = new Dictionary<string, string>
        {
            ["query"] = query.SearchText.Trim(),
            ["availability"] = query.Availability == PublicAvailabilityFilter.OpenOnly ? "open" : "all",
            ["game"] = query.Game switch
            {
                PublicGameFilter.FireRed => "FireRed",
                PublicGameFilter.LeafGreen => "LeafGreen",
                _ => "",
            },
            ["language"] = query.Language switch
            {
                PublicLanguageFilter.English => "English",
                PublicLanguageFilter.Japanese => "Japanese",
                PublicLanguageFilter.French => "French",
                PublicLanguageFilter.German => "German",
                PublicLanguageFilter.Italian => "Italian",
                PublicLanguageFilter.Spanish => "Spanish",
                _ => "",
            },
            ["sort"] = query.Sort switch
            {
                PublicSortOrder.Oldest => "oldest",
                PublicSortOrder.RoomName => "name",
                _ => "recent",
            },
            ["limit"] = "50",
        };
        var path = "/api/v1/public-trade-rooms?" + string.Join("&", parameters.Select(item =>
            $"{Uri.EscapeDataString(item.Key)}={Uri.EscapeDataString(item.Value)}"));
        try
        {
            using var response = await _http.GetAsync(path, cancellationToken);
            await EnsureSuccess(response, cancellationToken);
            var directory = await response.Content.ReadFromJsonAsync<PublicDirectoryDto>(
                JsonOptions, cancellationToken);
            if (directory?.ContractVersion != "public-directory.v1")
                throw new UserFacingException(
                    "Public rooms are not available with this SwitchTrade service.",
                    "public_directory_incompatible");
            return (directory.Rooms ?? []).Select(ToPublicRoom).ToArray();
        }
        catch (HttpRequestException)
        {
            throw new UserFacingException(
                "Public rooms are temporarily unavailable.", "public_directory_unavailable");
        }
        catch (JsonException)
        {
            throw new UserFacingException(
                "Public rooms returned an incomplete response.", "invalid_response");
        }
    }

    public async Task<TradeRoomInfo> JoinPublicRoomAsync(
        string listingId, string trainerDisplayName, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<RoomResponse>(
            $"/api/v1/public-trade-rooms/{Uri.EscapeDataString(listingId)}/join",
            new { trainer_display_name = trainerDisplayName.Trim() }, cancellationToken);
        return ToTradeRoom(result.Room);
    }

    public async Task StartConnectionAsync(
        SwitchRoomRole role, RoomMembershipRole membershipRole,
        string roomCode, CancellationToken cancellationToken = default)
    {
        var switchRoomRole = role switch
        {
            SwitchRoomRole.Creator => "creator",
            SwitchRoomRole.Finder => "finder",
            _ => throw new UserFacingException(
                "Choose Group Leader or Joining before connecting.", "switch_role_required"),
        };
        _ = await PostAsync<JsonElement>("/api/v1/trade-room/connect",
            new { switch_room_role = switchRoomRole }, cancellationToken);
    }

    public async Task<AuthoritativeRoomProjection?> TryGetTradeRoomAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.GetAsync("/api/v1/trade-room", cancellationToken);
            if (!response.IsSuccessStatusCode)
            {
                try
                {
                    var problem = await response.Content.ReadFromJsonAsync<ProblemDto>(
                        JsonOptions, cancellationToken);
                    if (problem?.Code is "room_not_active" or "room_not_found")
                        return new(0, 0, "closed", RoomMembershipRole.Member,
                            SwitchRoomRole.Unassigned, false, false, "none", false);
                    if (problem?.Code is "reconnect_credential_invalid" or "reconnect_deadline_expired")
                        throw ProblemException(problem);
                }
                catch (JsonException) { }
                catch (NotSupportedException) { }
                return null;
            }
            var room = await response.Content.ReadFromJsonAsync<AuthorityRoomDto>(JsonOptions, cancellationToken);
            if (room is null) return null;
            var local = room.Members?.FirstOrDefault(member => member.IsLocal);
            var partner = room.Members?.FirstOrDefault(member => !member.IsLocal);
            var membership = room.OwnerMemberId == room.LocalMemberId
                ? RoomMembershipRole.Owner : RoomMembershipRole.Member;
            var selectedRole = room.Attempt?.LocalSwitchRole ?? local?.SwitchRoomRole;
            var switchRole = selectedRole?.ToLowerInvariant() switch
            {
                "creator" => SwitchRoomRole.Creator,
                "finder" => SwitchRoomRole.Finder,
                _ => SwitchRoomRole.Unassigned,
            };
            var active = room.Members?.Where(member => member.OnlineState != "left").ToArray() ?? [];
            return new(room.RoomVersion, active.Length, room.State ?? "waiting_for_partner", membership,
                switchRole, partner?.OnlineState == "online",
                active.Length == 2 && active.All(member => member.ReadyState == "ready"),
                room.Attempt?.Phase ?? "none", room.Attempt?.RoleLocked == true,
                ToTradeRoom(room), room.Attempt?.Failure?.Code, room.Attempt?.Failure?.Stage,
                room.Attempt?.Failure?.Recoverable == true,
                room.Attempt?.Failure?.PrimaryAction);
        }
        catch (HttpRequestException) { return null; }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested) { return null; }
        catch (JsonException) { return null; }
        catch (NotSupportedException) { return null; }
    }

    public async Task StopConnectionAsync(CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>("/api/v1/session/stop", new { }, cancellationToken);

    public async Task ReleaseTradeRoomAsync(
        string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default)
    {
        var path = role == RoomMembershipRole.Owner
            ? "/api/v1/trade-room"
            : "/api/v1/trade-room/members/me";
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

    public async Task AbandonLocalAuthorityAsync(CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.DeleteAsync(
                "/api/v1/trade-room/local-authority", cancellationToken);
            await EnsureSuccess(response, cancellationToken);
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
                var friendly = profile.Model ?? "USB Wi-Fi adapter";
                var supported = profile.Status is "production-verified" or "beta-candidate";
                var experimental = profile.Experimental;
                var label = profile.Status switch
                {
                    "production-verified" => "Production verified",
                    "beta-candidate" => "Beta candidate",
                    "upstream-candidate" => "Research candidate",
                    "driver-candidate" => "Driver candidate",
                    "quarantined" => "Quarantined",
                    _ => "Needs review",
                };
                return new AdapterProfileViewData(
                    profile.UsbId ?? "unknown",
                    friendly, label,
                    supported ? "Available for the current beta workflow; two-adapter certification is pending."
                              : experimental
                                  ? "Experimental and untested with SwitchTrade; it may not connect or trade reliably. Diagnostics are available."
                                  : "Blocked from trading; retained for diagnostic evidence only.",
                    $"USB {profile.UsbId?.ToUpperInvariant()} · {profile.Chipset ?? "Unknown chipset"} · " +
                    $"{string.Join(", ", profile.Roles ?? [])} · engine {profile.HostEngine ?? "ldn"}",
                    supported || experimental, experimental, profile.HostEngine ?? "ldn");
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

    public async Task<HardwareDiagnosticViewData> RunHardwareDiagnosticsAsync(
        string usbId, CancellationToken cancellationToken = default)
    {
        var result = await PostAsync<HardwareDiagnosticResponse>(
            "/api/v1/hardware/diagnostics",
            new { usb_id = usbId, mode = "quick", role = "host" }, cancellationToken);
        var report = result.Report ?? throw new UserFacingException(
            "SwitchTrade received an incomplete diagnostic report.", "invalid_response");
        var first = report.Incompatibilities is { Count: > 0 } ? report.Incompatibilities[0] : null;
        var summary = first is null
            ? "Software checks completed. Physical Switch checks remain separate."
            : $"{first.Code}: {first.Action}";
        return new HardwareDiagnosticViewData(
            report.RunId ?? "unknown", report.OverallStatus ?? "unknown", summary,
            result.ReportPath ?? "Diagnostic report created");
    }

    public async Task<IReadOnlyList<HardwareDeviceViewData>> GetHardwareDevicesAsync(
        CancellationToken cancellationToken = default)
    {
        try
        {
            using var response = await _http.GetAsync("/api/v1/hardware/devices", cancellationToken);
            await EnsureSuccess(response, cancellationToken);
            var result = await response.Content.ReadFromJsonAsync<HardwareDevicesResponse>(JsonOptions, cancellationToken);
            if (result?.Devices is null || result.Devices.Any(device => device is null ||
                    string.IsNullOrWhiteSpace(device.BusId) ||
                    string.IsNullOrWhiteSpace(device.InstanceId) ||
                    string.IsNullOrWhiteSpace(device.UsbId)))
                throw InventoryFailure(
                    "Windows USB inventory returned an incomplete response.", "usb_inventory_invalid");
            return result.Devices.Select(device => new HardwareDeviceViewData(
                device.BusId!, device.InstanceId!, device.UsbId!,
                device.Description ?? device.Model ?? "USB Wi-Fi adapter",
                device.Status switch
                {
                    "production-verified" => "Production verified",
                    "beta-candidate" => "Beta candidate",
                    "upstream-candidate" or "driver-candidate" => "Experimental",
                    _ => "Blocked",
                },
                device.Selectable, device.Experimental, device.Attached, device.Selected)).ToArray();
        }
        catch (HttpRequestException)
        {
            throw InventoryFailure("Windows USB inventory is unavailable.", "usb_inventory_unavailable");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw InventoryFailure("Windows USB inventory took too long to respond.", "usb_inventory_timeout");
        }
        catch (JsonException)
        {
            throw InventoryFailure(
                "Windows USB inventory returned an incomplete response.", "usb_inventory_invalid");
        }
        catch (NotSupportedException)
        {
            throw InventoryFailure(
                "Windows USB inventory returned an incompatible response.", "usb_inventory_invalid");
        }
    }

    public async Task SelectHardwareDeviceAsync(
        string usbId, string instanceId, string busId, CancellationToken cancellationToken = default) =>
        _ = await PostAsync<JsonElement>("/api/v1/hardware/selection",
            new { usb_id = usbId, instance_id = instanceId, bus_id = busId }, cancellationToken);

    private static UserFacingException InventoryFailure(string message, string code) =>
        new(message + " The last known adapter list is retained; run read-only diagnostics or check again.",
            code, "hardware", recoverable: true, primaryAction: "run_hardware_diagnostics");

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

    private static PartyViewData? ParseParty(
        JsonElement parties, string seat, string heading, string accent)
    {
        if (!parties.TryGetProperty(seat, out var party) ||
            Text(party, "status") != "available" ||
            !party.TryGetProperty("snapshot", out var snapshot) ||
            snapshot.ValueKind != JsonValueKind.Object ||
            !snapshot.TryGetProperty("slots", out var slots)) return null;
        var result = new List<PokemonPartySlotViewData>();
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
            var moves = new List<MoveViewData>();
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
                new TrainerViewData(
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
        ProblemDto? problem = null;
        try
        {
            problem = await response.Content.ReadFromJsonAsync<ProblemDto>(JsonOptions, cancellationToken);
        }
        catch (JsonException) { }
        catch (NotSupportedException) { }

        throw ProblemException(problem);
    }

    private static UserFacingException ProblemException(ProblemDto? problem)
    {
        var message = problem?.Code switch
        {
            "adapter_disconnected" => "The selected adapter is no longer connected.",
            "adapter_quarantined" => "This adapter is quarantined and cannot trade.",
            "adapter_selection_required" => "Select an available Wi-Fi adapter in Settings.",
            "adapter_attach_failed" => "The selected adapter could not be attached. Run Repair adapter and try again.",
            "waiting_for_partner_role" => "Waiting for your partner to choose their Switch role.",
            "complementary_role_required" or "role_choice_conflict" =>
                "Choose opposite Switch roles: one Group Leader and one Joining.",
            "room_full" => "This Trade Room already has two players.",
            "room_not_found" or "not_found" => "We couldn’t find that Trade Room. Check the code and try again.",
            "room_not_active" => "This Trade Room is no longer active.",
            "reconnect_credential_invalid" =>
                "SwitchTrade can no longer verify the saved Trade Room access.",
            "reconnect_deadline_expired" =>
                "The saved Trade Room reconnect window expired.",
            "room_already_active" =>
                "An existing Trade Room is still active. Resume or leave it before opening another.",
            "relay_contract_incompatible" or "relay_capability_missing" =>
                "The online room service must be updated before trading.",
            "relay_unavailable" or "relay_internal_error" or "control_unavailable" =>
                "Online rooms are temporarily unavailable.",
            "room_version_conflict" or "state_conflict" => "The Trade Room changed. Refresh it and try again.",
            _ => "SwitchTrade couldn’t complete that action. Try again.",
        };
        return new UserFacingException(
            message, problem?.Code ?? "unknown_error", problem?.Stage,
            problem?.Recoverable ?? false, problem?.PrimaryAction, problem?.CorrelationId);
    }

    private static TradeRoomInfo ToTradeRoom(AuthorityRoomDto? room, string offering = "",
        string wanted = "", string note = "")
    {
        offering = string.IsNullOrWhiteSpace(offering) ? room?.Directory?.Offering ?? "" : offering;
        wanted = string.IsNullOrWhiteSpace(wanted) ? room?.Directory?.Wanted ?? "" : wanted;
        note = string.IsNullOrWhiteSpace(note) ? room?.Directory?.Note ?? "" : note;
        return new(
        room?.Name ?? "Private Trade Room", room?.RoomCode ?? "",
        room?.Visibility ?? "private",
        room?.Members?.Count(member => member.OnlineState != "left") ?? 1,
        "authoritative", room?.Profile?.OwnerDisplayName ?? "",
        ParseGame(room?.Profile?.Game), ParseLanguage(room?.Profile?.Language),
        offering, wanted, note);
    }

    private static PublicRoomListing ToPublicRoom(PublicRoomDto room) => new(
        room.ListingId ?? "", room.RoomName ?? "Trade Room",
        room.TrainerDisplayName ?? "Trainer", ParseGame(room.Game), ParseLanguage(room.Language),
        room.Offering ?? "", room.Wanted ?? "",
        string.Equals(room.Availability, "open", StringComparison.OrdinalIgnoreCase)
            ? PublicRoomAvailability.Open : PublicRoomAvailability.Full,
        room.Occupancy, room.Capacity <= 0 ? 2 : room.Capacity,
        DateTimeOffset.TryParse(room.CreatedAt, out var created) ? created : DateTimeOffset.MinValue,
        room.Note ?? "");

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
        [property: JsonPropertyName("release_id")] string? ReleaseId,
        bool Compatible,
        [property: JsonPropertyName("run_id")] string? RunId,
        [property: JsonPropertyName("endpoint_process_running")] bool EndpointProcessRunning,
        [property: JsonPropertyName("session_id")] string? SessionId,
        IReadOnlyDictionary<string, ReadinessAxisDto>? States,
        FailureDto? Failure,
        IReadOnlyList<string>? Capabilities);
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
    private sealed record RoomResponse(
        [property: JsonPropertyName("contract_version")] string? ContractVersion,
        AuthorityRoomDto? Room);
    private sealed record AuthorityRoomDto(
        [property: JsonPropertyName("room_id")] string? RoomId,
        [property: JsonPropertyName("room_version")] int RoomVersion,
        string? Name,
        string? Visibility,
        [property: JsonPropertyName("room_code")] string? RoomCode,
        RoomProfileDto? Profile,
        [property: JsonPropertyName("owner_member_id")] string? OwnerMemberId,
        [property: JsonPropertyName("local_member_id")] string? LocalMemberId,
        string? State,
        IReadOnlyList<AuthorityMemberDto>? Members,
        AuthorityAttemptDto? Attempt,
        AuthorityDirectoryDto? Directory);
    private sealed record AuthorityDirectoryDto(string? Offering, string? Wanted, string? Note);
    private sealed record RoomProfileDto(
        [property: JsonPropertyName("owner_display_name")] string? OwnerDisplayName,
        string? Game,
        string? Language);
    private sealed record AuthorityMemberDto(
        [property: JsonPropertyName("member_id")] string? MemberId,
        string? Seat,
        [property: JsonPropertyName("is_local")] bool IsLocal,
        [property: JsonPropertyName("online_state")] string? OnlineState,
        [property: JsonPropertyName("ready_state")] string? ReadyState,
        [property: JsonPropertyName("switch_room_role")] string? SwitchRoomRole);
    private sealed record AuthorityAttemptDto(
        [property: JsonPropertyName("local_switch_role")] string? LocalSwitchRole,
        string? Phase,
        [property: JsonPropertyName("role_locked")] bool RoleLocked,
        AttemptFailureDto? Failure);
    private sealed record AttemptFailureDto(
        string? Code,
        string? Stage,
        bool Recoverable,
        [property: JsonPropertyName("primary_action")] string? PrimaryAction);
    private sealed record PublicDirectoryDto(
        [property: JsonPropertyName("contract_version")] string? ContractVersion,
        IReadOnlyList<PublicRoomDto>? Rooms,
        [property: JsonPropertyName("next_cursor")] string? NextCursor);
    private sealed record PublicRoomDto(
        [property: JsonPropertyName("listing_id")] string? ListingId,
        [property: JsonPropertyName("room_name")] string? RoomName,
        [property: JsonPropertyName("trainer_display_name")] string? TrainerDisplayName,
        string? Game,
        string? Language,
        string? Offering,
        string? Wanted,
        string? Note,
        string? Availability,
        int Occupancy,
        int Capacity,
        [property: JsonPropertyName("created_at")] string? CreatedAt);
    private sealed record ProfilesResponse(IReadOnlyList<ProfileDto>? Profiles);
    private sealed record ProfileDto(
        [property: JsonPropertyName("usb_id")] string? UsbId,
        string? Status,
        IReadOnlyList<string>? Roles,
        string? Model,
        string? Chipset,
        [property: JsonPropertyName("host_engine")] string? HostEngine,
        bool Experimental);
    private sealed record HardwareDiagnosticResponse(
        HardwareDiagnosticReportDto? Report,
        [property: JsonPropertyName("report_path")] string? ReportPath);
    private sealed record HardwareDiagnosticReportDto(
        [property: JsonPropertyName("run_id")] string? RunId,
        [property: JsonPropertyName("overall_status")] string? OverallStatus,
        IReadOnlyList<HardwareIncompatibilityDto>? Incompatibilities);
    private sealed record HardwareIncompatibilityDto(string? Code, string? Action);
    private sealed record HardwareDevicesResponse(IReadOnlyList<HardwareDeviceDto>? Devices);
    private sealed record HardwareDeviceDto(
        [property: JsonPropertyName("bus_id")] string? BusId,
        [property: JsonPropertyName("instance_id")] string? InstanceId,
        [property: JsonPropertyName("usb_id")] string? UsbId,
        string? Description,
        string? Model,
        string? Status,
        bool Selectable,
        bool Experimental,
        bool Attached,
        bool Selected);
    private sealed record SupportBundleResponse(string? Path);
    private sealed record ProblemDto(
        string? Code,
        string? Message,
        string? Detail,
        string? Stage,
        bool Recoverable,
        [property: JsonPropertyName("primary_action")] string? PrimaryAction,
        [property: JsonPropertyName("correlation_id")] string? CorrelationId);
}
