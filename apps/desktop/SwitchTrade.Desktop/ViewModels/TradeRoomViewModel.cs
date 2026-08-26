using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.State;

namespace SwitchTrade.Desktop.ViewModels;

public sealed class TradeRoomScreenViewModel : ScreenViewModel, IDisposable
{
    private readonly ActiveTradeRoomCoordinator _coordinator;
    private readonly HashSet<string> _seenCommits = [];
    private PokemonPartySlotViewData? _selectedPokemon;
    private string _tradeCommitStatus = "";

    public TradeRoomScreenViewModel(MainViewModel shell, ActiveTradeRoomCoordinator coordinator) : base(shell)
    {
        _coordinator = coordinator;
        _coordinator.Changed += CoordinatorChanged;
        ConnectionCommand = new AsyncCommand(ToggleConnectionAsync, CanToggleConnection);
        RepairAdapterCommand = new AsyncCommand(shell.RepairAdapterAsync, () => HasAdapterRepair);
        LeaveCommand = new AsyncCommand(LeaveAsync, () => !_coordinator.IsPending);
        CopyCodeCommand = new RelayCommand(() => Shell.Copy(RoomCode, "Room code copied"));
        CopyInvitationCommand = new RelayCommand(() => Shell.Copy(InvitationText, "Invitation copied"));
        SelectPokemonCommand = new RelayCommand<PokemonPartySlotViewData>(pokemon => SelectedPokemon = pokemon,
            pokemon => pokemon is not null && !pokemon.IsEmpty);
        ClearPokemonCommand = new RelayCommand(() => SelectedPokemon = null);
    }

    public override string Title => "Trade Room";
    private ActiveTradeRoomContext? Context => _coordinator.Context;
    public string RoomName => Context?.Room.Name ?? "Trade Room";
    public string RoomCode => Context?.Room.RoomCode ?? "";
    public string VisibilityLabel => string.Equals(
        Context?.Room.Visibility, "public", StringComparison.OrdinalIgnoreCase) ? "Public" : "Private";
    public bool HasRoomCode => !string.IsNullOrWhiteSpace(RoomCode);
    public bool IsOwner => Context?.MembershipRole == RoomMembershipRole.Owner;
    public string MembershipActionText => IsOwner ? "Close Trade Room" : "Leave Trade Room";
    public string YouSummary => YouParty is null ? "Party data unavailable" : "Checksum-verified party";
    public string PartnerSummary => PartnerParty is null ? "Party data unavailable" : "Checksum-verified party";
    public string MainInstruction => Context?.SwitchRole == SwitchRoomRole.Unassigned
            ? "Both trainers can press Connect this Switch. SwitchTrade will assign one creator safely."
        : Context?.SwitchRole == SwitchRoomRole.Creator
            ? "Create the room on your Switch"
            : "Find your partner’s room";
    public string InstructionDetails => Context?.SwitchRole == SwitchRoomRole.Unassigned
            ? "When both trainers are ready, SwitchTrade will show each person the correct create or find instruction."
        : Context?.SwitchRole == SwitchRoomRole.Creator
            ? "Open Direct Connection in the game and create a room. Keep it open while SwitchTrade looks for it."
            : "Open room search in Direct Connection and keep the results open while SwitchTrade prepares your partner’s room.";
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The notice is a bindable property of the screen projection.")]
    public string LimitationNotice =>
        "Room membership, readiness, and creator assignment are synchronized by SwitchTrade’s online room service.";
    public string ConnectionActionText => _coordinator.ConnectionState == LegacyConnectionState.Idle
        ? "Connect this Switch"
        : "End connection";
    public string ConnectionStatus => _coordinator.StatusText;
    public bool IsConnectionPending => _coordinator.IsPending;
    public bool HasRecovery => !string.IsNullOrWhiteSpace(_coordinator.RecoveryMessage);
    public bool HasAdapterRepair => HasRecovery && Shell.RecoveryTechnicalDetails.Contains(
        "radio.failed", StringComparison.OrdinalIgnoreCase);
    public string RecoveryMessage => _coordinator.RecoveryMessage ?? "";
    public string StageHeading => _coordinator.ConnectionState == LegacyConnectionState.Active
            ? "Both Switches are connected"
            : MainInstruction;
    public string LinklineState => _coordinator.ConnectionState switch
    {
        LegacyConnectionState.Active => "Connected",
        LegacyConnectionState.Starting => "Connecting",
        LegacyConnectionState.Ending or LegacyConnectionState.ClosingRoom => "Ending",
        LegacyConnectionState.NeedsRecovery => "Needs attention",
        _ => "Not connected",
    };
    public string InvitationText
    {
        get
        {
            var invitation = Context?.LocalInvitation;
            var message = $"Join my SwitchTrade room “{RoomName}” with code {RoomCode}.";
            if (invitation is null) return message;
            if (!string.IsNullOrWhiteSpace(invitation.Offering)) message += $" Offering: {invitation.Offering}.";
            if (!string.IsNullOrWhiteSpace(invitation.Wanted)) message += $" Looking for: {invitation.Wanted}.";
            if (!string.IsNullOrWhiteSpace(invitation.Note)) message += $" Note: {invitation.Note}";
            return message;
        }
    }
    public PartyViewData? YouParty { get; private set; }
    public PartyViewData? PartnerParty { get; private set; }
    public bool HasPartyData => YouParty is not null || PartnerParty is not null;
    public string TradeCommitStatus
    {
        get => _tradeCommitStatus;
        private set
        {
            if (!Set(ref _tradeCommitStatus, value)) return;
            OnPropertyChanged(nameof(HasTradeCommit));
        }
    }
    public bool HasTradeCommit => !string.IsNullOrWhiteSpace(TradeCommitStatus);
    public PokemonPartySlotViewData? SelectedPokemon
    {
        get => _selectedPokemon;
        private set
        {
            if (!Set(ref _selectedPokemon, value)) return;
            OnPropertyChanged(nameof(HasSelectedPokemon));
        }
    }
    public bool HasSelectedPokemon => SelectedPokemon is not null;
    public AsyncCommand ConnectionCommand { get; }
    public AsyncCommand RepairAdapterCommand { get; }
    public AsyncCommand LeaveCommand { get; }
    public RelayCommand CopyCodeCommand { get; }
    public RelayCommand CopyInvitationCommand { get; }
    public RelayCommand<PokemonPartySlotViewData> SelectPokemonCommand { get; }
    public RelayCommand ClearPokemonCommand { get; }

    private bool CanToggleConnection() => IsServiceReady && !_coordinator.IsPending && _coordinator.HasRoom;

    private async Task ToggleConnectionAsync()
    {
        if (_coordinator.ConnectionState == LegacyConnectionState.Idle)
            await _coordinator.StartConnectionAsync();
        else
            await _coordinator.StopConnectionAsync();
    }

    private async Task LeaveAsync()
    {
        if (await Shell.ConfirmAndReleaseRoomAsync()) Shell.ShowHome();
    }

    public void ApplyLiveParties(LivePartyProjection projection)
    {
        var localIsA = Context?.MembershipRole == RoomMembershipRole.Owner;
        YouParty = localIsA ? projection.MemberA : projection.MemberB;
        PartnerParty = localIsA ? projection.MemberB : projection.MemberA;
        OnPropertyChanged(nameof(YouParty));
        OnPropertyChanged(nameof(PartnerParty));
        OnPropertyChanged(nameof(HasPartyData));
        OnPropertyChanged(nameof(YouSummary));
        OnPropertyChanged(nameof(PartnerSummary));
        if (projection.TradingRoomConfirmed && YouParty is not null && PartnerParty is not null)
            Shell.Announce("Both verified parties are available.");
        foreach (var commit in projection.Commits.Where(commit => _seenCommits.Add(commit.CommitId)))
        {
            TradeCommitStatus = $"Trade {commit.TradeIndex} completed and was verified after saving.";
            Shell.Announce(TradeCommitStatus);
        }
    }

    private void CoordinatorChanged(object? sender, EventArgs e)
    {
        OnPropertyChanged(nameof(RoomName));
        OnPropertyChanged(nameof(RoomCode));
        OnPropertyChanged(nameof(IsOwner));
        OnPropertyChanged(nameof(MembershipActionText));
        OnPropertyChanged(nameof(MainInstruction));
        OnPropertyChanged(nameof(InstructionDetails));
        OnPropertyChanged(nameof(ConnectionActionText));
        OnPropertyChanged(nameof(ConnectionStatus));
        OnPropertyChanged(nameof(IsConnectionPending));
        OnPropertyChanged(nameof(HasRecovery));
        OnPropertyChanged(nameof(HasAdapterRepair));
        OnPropertyChanged(nameof(RecoveryMessage));
        OnPropertyChanged(nameof(StageHeading));
        OnPropertyChanged(nameof(LinklineState));
        ConnectionCommand.RaiseCanExecuteChanged();
        RepairAdapterCommand.RaiseCanExecuteChanged();
        LeaveCommand.RaiseCanExecuteChanged();
    }

    public override bool DismissTemporaryLayer()
    {
        if (SelectedPokemon is null) return false;
        SelectedPokemon = null;
        return true;
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        ConnectionCommand.RaiseCanExecuteChanged();
    }

    public void Dispose()
    {
        _coordinator.Changed -= CoordinatorChanged;
    }
}
