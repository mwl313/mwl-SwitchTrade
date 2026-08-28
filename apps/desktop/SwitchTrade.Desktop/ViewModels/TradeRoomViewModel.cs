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
        GroupLeaderCommand = new AsyncCommand(
            () => ChooseRoleAsync(SwitchRoomRole.Creator), CanChooseRole);
        JoiningCommand = new AsyncCommand(
            () => ChooseRoleAsync(SwitchRoomRole.Finder), CanChooseRole);
        ConnectionCommand = new AsyncCommand(
            () => _coordinator.StopConnectionAsync(), CanEndConnection);
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
    public string YouSummary => YouParty is null ? "" : "Checksum-verified party";
    public string PartnerSummary => PartnerParty is null ? "" : "Checksum-verified party";
    public string YouPresenceText => $"Online: {_coordinator.LocalTrainerDisplayName}";
    public string PartnerPresenceText => _coordinator.PartnerOnline
        ? $"Online: {(_coordinator.PartnerTrainerDisplayName.Length > 0 ? _coordinator.PartnerTrainerDisplayName : "Trainer")}"
        : "Waiting...";
    public bool PartnerOnline => _coordinator.PartnerOnline;
    public string ConnectionStatus => _coordinator.StatusText;
    public bool IsConnectionPending => _coordinator.IsPending;
    public bool ShowRoleChoices => _coordinator.ConnectionState == LegacyConnectionState.Idle;
    public bool ShowEndConnection => !ShowRoleChoices;
    public bool HasRecovery => !string.IsNullOrWhiteSpace(_coordinator.RecoveryMessage);
    public bool HasAdapterRepair => HasRecovery && RecoveryCode != "radio.switch_room_not_found" && RecoveryStage is
        "hardware_share" or "hardware_attach" or "radio";
    public string AdapterRecoveryLabel => RecoveryCode == "adapter_not_shared"
        ? "Authorize adapter"
        : "Repair adapter";
    public string RecoveryMessage => _coordinator.RecoveryMessage ?? "";
    public string RecoveryCode => _coordinator.RecoveryCode ?? "";
    public string RecoveryStage => _coordinator.RecoveryStage ?? "";
    public bool RecoveryRecoverable => _coordinator.RecoveryRecoverable;
    public string RecoveryAction => _coordinator.RecoveryAction ?? "";
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
    public AsyncCommand GroupLeaderCommand { get; }
    public AsyncCommand JoiningCommand { get; }
    public AsyncCommand RepairAdapterCommand { get; }
    public AsyncCommand LeaveCommand { get; }
    public RelayCommand CopyCodeCommand { get; }
    public RelayCommand CopyInvitationCommand { get; }
    public RelayCommand<PokemonPartySlotViewData> SelectPokemonCommand { get; }
    public RelayCommand ClearPokemonCommand { get; }

    private bool CanChooseRole() => IsServiceReady && !_coordinator.IsPending &&
                                    _coordinator.HasRoom && _coordinator.PartnerOnline;
    private bool CanEndConnection() => IsServiceReady && !_coordinator.IsPending &&
                                       _coordinator.HasRoom && !ShowRoleChoices;

    private Task<bool> ChooseRoleAsync(SwitchRoomRole role) => _coordinator.StartConnectionAsync(role);

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
        OnPropertyChanged(nameof(YouPresenceText));
        OnPropertyChanged(nameof(PartnerPresenceText));
        OnPropertyChanged(nameof(PartnerOnline));
        OnPropertyChanged(nameof(ConnectionStatus));
        OnPropertyChanged(nameof(IsConnectionPending));
        OnPropertyChanged(nameof(ShowRoleChoices));
        OnPropertyChanged(nameof(ShowEndConnection));
        OnPropertyChanged(nameof(HasRecovery));
        OnPropertyChanged(nameof(HasAdapterRepair));
        OnPropertyChanged(nameof(AdapterRecoveryLabel));
        OnPropertyChanged(nameof(RecoveryMessage));
        OnPropertyChanged(nameof(RecoveryCode));
        OnPropertyChanged(nameof(RecoveryStage));
        OnPropertyChanged(nameof(RecoveryRecoverable));
        OnPropertyChanged(nameof(RecoveryAction));
        OnPropertyChanged(nameof(LinklineState));
        ConnectionCommand.RaiseCanExecuteChanged();
        GroupLeaderCommand.RaiseCanExecuteChanged();
        JoiningCommand.RaiseCanExecuteChanged();
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
        GroupLeaderCommand.RaiseCanExecuteChanged();
        JoiningCommand.RaiseCanExecuteChanged();
    }

    public void Dispose()
    {
        _coordinator.Changed -= CoordinatorChanged;
    }
}
