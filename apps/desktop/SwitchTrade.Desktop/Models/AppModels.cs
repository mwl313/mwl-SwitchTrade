namespace SwitchTrade.Desktop.Models;

public sealed record ControlStatus(
    string Status,
    string Version,
    string RunId,
    bool EndpointProcessRunning,
    bool RadioChecked,
    bool TunnelConnected,
    string? SessionId,
    string? Error,
    string ContractVersion = "legacy.status",
    bool Compatible = false,
    IReadOnlyDictionary<string, ReadinessAxis>? States = null,
    string? FailureStage = null,
    string? RecoveryAction = null,
    IReadOnlyList<string>? Capabilities = null,
    string? ReleaseId = null,
    string? FailureCode = null)
{
    public ReadinessAxis Axis(string name) => States is not null && States.TryGetValue(name, out var axis)
        ? axis
        : new ReadinessAxis("unknown", "Not checked", $"{name}.unknown", null);
    public bool HasCapability(string capability) =>
        Capabilities?.Contains(capability, StringComparer.Ordinal) == true;
}

public sealed record ReadinessAxis(
    string Status,
    string UserMessage,
    string TechnicalCode,
    string? PrimaryAction)
{
    public string Display => Status switch
    {
        "ready" => "Ready",
        "checking" => "Checking",
        "degraded" => "Degraded",
        "blocked" => "Blocked",
        "failed" => "Failed",
        "unavailable" => "Not active",
        _ => "Not checked",
    };
}

public enum SwitchRoomRole { Unassigned, Creator, Finder }
public enum RoomMembershipRole { Owner, Member }
public enum GameVersionChoice { None, FireRed, LeafGreen }
public enum GameLanguage { None, English, Japanese, French, German, Italian, Spanish }
public enum TradeRoomVisibility { Private, Public }

public sealed record SelectionOption<T>(T Value, string Label)
{
    public override string ToString() => Label;
}

public sealed record TradeRoomCreateRequest(
    string RoomName,
    string TrainerDisplayName,
    GameVersionChoice Game,
    GameLanguage Language,
    TradeRoomVisibility Visibility,
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
    string Note = "",
    string LocalTrainerDisplayName = "",
    string PartnerTrainerDisplayName = "");

public sealed record AuthoritativeRoomProjection(
    int RoomVersion,
    int Participants,
    string State,
    RoomMembershipRole MembershipRole,
    SwitchRoomRole SwitchRole,
    bool PartnerOnline,
    bool BothReady,
    string AttemptPhase,
    bool RoleLocked,
    TradeRoomInfo? Room = null,
    string? FailureCode = null,
    string? FailureStage = null,
    bool FailureRecoverable = false,
    string? FailureAction = null,
    string LocalTrainerDisplayName = "",
    string PartnerTrainerDisplayName = "");

public sealed record AdapterProfileViewData(
    string UsbId,
    string FriendlyName,
    string SupportLabel,
    string Summary,
    string TechnicalDetails,
    bool IsSelectable,
    bool IsExperimental,
    string HostEngine);

public sealed record HardwareDiagnosticViewData(
    string RunId,
    string OverallStatus,
    string Summary,
    string ReportPath);

public enum ProductionDiagnosticTest { Automated, RoomDetection, ApAssociation, Recommended }

public sealed record ProductionDiagnosticStageViewData(
    string Name,
    string Status,
    string Code,
    string Message);

public sealed record ProductionDiagnosticCheckpointViewData(
    string Id,
    string Instructions,
    DateTimeOffset? Deadline);

public sealed record ProductionDiagnosticViewData(
    string RunId,
    ProductionDiagnosticTest Test,
    string Status,
    string CurrentStage,
    string? ResultLevel,
    string? FailureCode,
    string? FailureMessage,
    ProductionDiagnosticCheckpointViewData? Checkpoint,
    IReadOnlyList<ProductionDiagnosticStageViewData> Stages,
    IReadOnlyList<string> Limitations)
{
    public bool IsTerminal => Status is "passed" or "partial" or "failed" or "canceled";
    public bool IsWaiting => Status == "awaiting_user" && Checkpoint is not null;
}

public sealed record HardwareDeviceViewData(
    string BusId,
    string InstanceId,
    string UsbId,
    string FriendlyName,
    string SupportLabel,
    bool IsSelectable,
    bool IsExperimental,
    bool IsShared,
    bool IsAttached,
    bool IsSelected)
{
    public string DisplayLabel => $"USB {BusId} · {FriendlyName} · {SupportLabel}";
    public string ConnectionGate => IsAttached ? "Attached to WSL" : IsShared
        ? "Authorized by Windows"
        : "Windows authorization required";
    public string Disclaimer => !IsSelectable
        ? "Quarantined — available for diagnostics only and blocked from trading."
        : IsExperimental
            ? $"Experimental — untested with SwitchTrade and may not work reliably. {ConnectionGate}."
            : $"Supported hardware profile. {ConnectionGate}.";
}

public enum PublicRoomAvailability { Open, Full }
public enum PublicSearchBy { AnyField, RoomName, Trainer, OfferedPokemon, WantedPokemon }
public enum PublicAvailabilityFilter { OpenOnly, AllRooms }
public enum PublicGameFilter { AnyGame, FireRed, LeafGreen }
public enum PublicLanguageFilter { AnyLanguage, English, Japanese, French, German, Italian, Spanish }
public enum PublicSortOrder { RecentlyOpened, Oldest, RoomName }

public sealed record PublicRoomQuery(
    string SearchText,
    PublicAvailabilityFilter Availability,
    PublicGameFilter Game,
    PublicLanguageFilter Language,
    PublicSortOrder Sort);

public sealed record PublicRoomListing(
    string ListingId,
    string RoomName,
    string TrainerDisplayName,
    GameVersionChoice Game,
    GameLanguage Language,
    string Offering,
    string Wanted,
    PublicRoomAvailability Availability,
    int OccupancyCount,
    int Capacity,
    DateTimeOffset CreatedAt,
    string Note)
{
    public string GameLabel => Game.ToString();
    public string LanguageLabel => Language.ToString();
    public string AvailabilityLabel => Availability.ToString();
    public string Occupancy => $"{OccupancyCount} of {Capacity}";
    public bool IsOpen => Availability == PublicRoomAvailability.Open && OccupancyCount < Capacity;
    public string AccessibleName =>
        $"{RoomName}, trainer {TrainerDisplayName}, {GameLabel}, {AvailabilityLabel}, {Occupancy}";
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

public sealed record MoveViewData(string Name, int? CurrentPp = null, int? MaxPp = null)
{
    public string Display => CurrentPp is null ? Name : $"{Name} · {CurrentPp}/{MaxPp} PP";
}

public sealed record TrainerViewData(string Name, int? TrainerId = null, GameLanguage Language = GameLanguage.None)
{
    public string Display => TrainerId is null ? Name : $"{Name} · ID {TrainerId:00000}";
}

public sealed record PokemonPartySlotViewData(
    string Nickname,
    string Species,
    int Level,
    string Nature,
    string? HeldItem,
    BattleStats? Stats,
    SixValues? Ivs,
    SixValues? Evs,
    IReadOnlyList<MoveViewData> Moves,
    TrainerViewData? Trainer,
    bool IsEmpty = false,
    bool IsLive = false)
{
    public string Initial => IsEmpty || string.IsNullOrWhiteSpace(Species) ? "—" : Species[..1];
    public string LevelText => IsEmpty ? "Empty slot" : $"Lv. {Level}";
    public string HeldItemText => string.IsNullOrWhiteSpace(HeldItem) ? "None" : HeldItem;
    public string StatsText => Stats?.Display ?? "Unavailable";
    public string IvsText => Ivs?.Display ?? "Unavailable";
    public string EvsText => Evs?.Display ?? "Unavailable";
    public string MovesText => Moves.Count == 0 ? "Unavailable" : string.Join(" · ", Moves.Select(move => move.Name));
    public string TrainerText => Trainer?.Display ?? "Unavailable";
    public string ValidityLabel => IsEmpty ? "No Pokémon" : IsLive ? "Checksum-verified data" : "Unavailable";
    public string AccessibleName => IsEmpty
        ? "Empty party slot"
        : $"View details for {Nickname}, {Species}, level {Level}";
}

public sealed record PartyViewData(
    string Heading,
    string Accent,
    IReadOnlyList<PokemonPartySlotViewData> Slots);

public sealed record LivePartyProjection(
    PartyViewData? MemberA,
    PartyViewData? MemberB,
    string ObserverStatus,
    bool TradingRoomConfirmed,
    IReadOnlyList<TradeCommitProjection> Commits);

public sealed record TradeCommitProjection(
    string CommitId,
    int TradeIndex,
    string Outcome,
    DateTimeOffset? CommittedAt);
