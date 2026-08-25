namespace SwitchTrade.Desktop.Models;

public sealed record ControlStatus(
    string Status,
    string Version,
    string RunId,
    bool EndpointProcessRunning,
    bool RadioChecked,
    bool TunnelConnected,
    string? SessionId,
    string? Error);

public sealed record TradeRoomInfo(
    string Name,
    string RoomCode,
    string Visibility,
    int Participants,
    string Scope);

public sealed record AdapterProfileViewData(
    string FriendlyName,
    string SupportLabel,
    string Summary,
    string TechnicalDetails,
    bool IsSupported);

public sealed record PublicRoomSummary(
    string RoomId,
    string RoomName,
    string TrainerDisplayName,
    string GameVersion,
    string Language,
    string Offering,
    string Wanted,
    string Region,
    string Availability,
    int LatencyMs,
    DateTimeOffset CreatedAt,
    string Note)
{
    public string ConnectionQuality => LatencyMs switch
    {
        < 65 => $"Excellent · {LatencyMs} ms",
        < 125 => $"Good · {LatencyMs} ms",
        _ => $"Fair · {LatencyMs} ms",
    };

    public string Occupancy => "1 of 2";
}

public sealed record PokemonViewData(
    string Nickname,
    string Species,
    int Level,
    string Nature,
    string HeldItem,
    string Stats,
    string Ivs,
    string Evs,
    string Moves,
    string Trainer,
    bool IsEmpty = false)
{
    public string Initial => IsEmpty || string.IsNullOrWhiteSpace(Species) ? "—" : Species[..1];
    public string LevelText => IsEmpty ? "Empty slot" : $"Lv. {Level}";
    public string Verification => IsEmpty ? "No Pokémon" : "Sample data";
    public string AccessibleName => IsEmpty
        ? "Empty party slot"
        : $"View sample details for {Nickname}, {Species}, level {Level}";
}

public sealed record PartyPanelViewData(string Heading, string Accent, IReadOnlyList<PokemonViewData> Slots);
