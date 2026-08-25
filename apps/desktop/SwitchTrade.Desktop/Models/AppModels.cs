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

public enum SwitchRoomRole { Creator, Finder }
public enum RoomMembershipRole { Owner, Member }
public enum GameVersionChoice { None, FireRed, LeafGreen }
public enum GameLanguage { None, English, Japanese, French, German, Italian, Spanish }

public sealed record SelectionOption<T>(T Value, string Label)
{
    public override string ToString() => Label;
}

public sealed record TradeRoomCreateRequest(
    string RoomName,
    string TrainerDisplayName,
    GameVersionChoice Game,
    GameLanguage Language,
    string Offering,
    string Wanted,
    string Note);

public sealed record TradeRoomInfo(
    string Name,
    string RoomCode,
    string Visibility,
    int Participants,
    string Scope,
    string TrainerDisplayName = "",
    GameVersionChoice Game = GameVersionChoice.None,
    GameLanguage Language = GameLanguage.None,
    string Offering = "",
    string Wanted = "",
    string Note = "");

public sealed record AdapterProfileViewData(
    string FriendlyName,
    string SupportLabel,
    string Summary,
    string TechnicalDetails,
    bool IsSupported);

public enum PreviewAvailability { Open, Full }
public enum PublicSearchBy { AnyField, RoomName, Trainer, OfferedPokemon, WantedPokemon }
public enum PublicAvailabilityFilter { OpenOnly, AllRooms }
public enum PublicGameFilter { AnyGame, FireRed, LeafGreen }
public enum PublicLanguageFilter { AnyLanguage, English, Japanese, French }
public enum PublicSortOrder { BestMatch, LowestLatency, RecentlyOpened }

public sealed record PublicRoomPreview(
    string PreviewId,
    string RoomName,
    string TrainerDisplayName,
    GameVersionChoice Game,
    GameLanguage Language,
    string Offering,
    string Wanted,
    string Region,
    PreviewAvailability Availability,
    int LatencyMs,
    DateTimeOffset CreatedAt,
    string Note)
{
    public string GameLabel => Game.ToString();
    public string LanguageLabel => Language.ToString();
    public string AvailabilityLabel => Availability.ToString();
    public string ConnectionQuality => LatencyMs switch
    {
        < 65 => $"Excellent · {LatencyMs} ms",
        < 125 => $"Good · {LatencyMs} ms",
        _ => $"Fair · {LatencyMs} ms",
    };
    public string Occupancy => Availability == PreviewAvailability.Open ? "1 of 2" : "2 of 2";
    public string AccessibleName =>
        $"{RoomName}, trainer {TrainerDisplayName}, {GameLabel}, {AvailabilityLabel}, {ConnectionQuality}";
}

public sealed record BattleStats(int Hp, int Attack, int Defense, int SpecialAttack, int SpecialDefense, int Speed)
{
    public string Display =>
        $"HP {Hp} · Atk {Attack} · Def {Defense} · SpA {SpecialAttack} · SpD {SpecialDefense} · Spe {Speed}";
}

public sealed record SixValues(int Hp, int Attack, int Defense, int SpecialAttack, int SpecialDefense, int Speed)
{
    public string Display => $"{Hp} / {Attack} / {Defense} / {SpecialAttack} / {SpecialDefense} / {Speed}";
}

public sealed record MovePreview(string Name, int? CurrentPp = null, int? MaxPp = null)
{
    public string Display => CurrentPp is null ? Name : $"{Name} · {CurrentPp}/{MaxPp} PP";
}

public sealed record TrainerPreview(string Name, int? TrainerId = null, GameLanguage Language = GameLanguage.None)
{
    public string Display => TrainerId is null ? Name : $"{Name} · ID {TrainerId:00000}";
}

public sealed record PokemonPreviewViewData(
    string Nickname,
    string Species,
    int Level,
    string Nature,
    string? HeldItem,
    BattleStats? Stats,
    SixValues? Ivs,
    SixValues? Evs,
    IReadOnlyList<MovePreview> Moves,
    TrainerPreview? Trainer,
    bool IsEmpty = false)
{
    public string Initial => IsEmpty || string.IsNullOrWhiteSpace(Species) ? "—" : Species[..1];
    public string LevelText => IsEmpty ? "Empty slot" : $"Lv. {Level}";
    public string HeldItemText => string.IsNullOrWhiteSpace(HeldItem) ? "None" : HeldItem;
    public string StatsText => Stats?.Display ?? "Unavailable";
    public string IvsText => Ivs?.Display ?? "Unavailable";
    public string EvsText => Evs?.Display ?? "Unavailable";
    public string MovesText => Moves.Count == 0 ? "Unavailable" : string.Join(" · ", Moves.Select(move => move.Name));
    public string TrainerText => Trainer?.Display ?? "Unavailable";
    public string ValidityLabel => IsEmpty ? "No Pokémon" : "Sample preview";
    public string AccessibleName => IsEmpty
        ? "Empty party slot"
        : $"View sample details for {Nickname}, {Species}, level {Level}";
}

public sealed record PartyPreviewViewData(
    string Heading,
    string Accent,
    IReadOnlyList<PokemonPreviewViewData> Slots);
