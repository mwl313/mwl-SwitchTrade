using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.State;

namespace SwitchTrade.Desktop.ViewModels;

public sealed class TradeRoomScreenViewModel : ScreenViewModel, IDisposable
{
    private readonly ActiveTradeRoomCoordinator? _coordinator;
    private PokemonPreviewViewData? _selectedPokemon;

    public TradeRoomScreenViewModel(MainViewModel shell, ActiveTradeRoomCoordinator coordinator) : base(shell)
    {
        _coordinator = coordinator;
        _coordinator.Changed += CoordinatorChanged;
        ConnectionCommand = new AsyncCommand(ToggleConnectionAsync, CanToggleConnection);
        LeaveCommand = new AsyncCommand(LeaveAsync, () => !_coordinator.IsPending);
        CopyCodeCommand = new RelayCommand(() => Shell.Copy(RoomCode, "Room code copied"));
        CopyInvitationCommand = new RelayCommand(() => Shell.Copy(InvitationText, "Invitation copied"));
        SelectPokemonCommand = new RelayCommand<PokemonPreviewViewData>(pokemon => SelectedPokemon = pokemon,
            pokemon => pokemon is not null && !pokemon.IsEmpty);
        ClearPokemonCommand = new RelayCommand(() => SelectedPokemon = null);
    }

    public TradeRoomScreenViewModel(MainViewModel shell, PublicRoomPreview preview) : base(shell)
    {
        DemoRoom = preview;
        var parties = shell.PreviewProvider.GetSampleParties();
        YouParty = parties.You;
        PartnerParty = parties.Partner;
        ConnectionCommand = new AsyncCommand(() => Task.CompletedTask, () => false);
        LeaveCommand = new AsyncCommand(() => shell.GoBackAsync());
        CopyCodeCommand = new RelayCommand(() => { }, () => false);
        CopyInvitationCommand = new RelayCommand(() => { }, () => false);
        SelectPokemonCommand = new RelayCommand<PokemonPreviewViewData>(pokemon => SelectedPokemon = pokemon,
            pokemon => pokemon is not null && !pokemon.IsEmpty);
        ClearPokemonCommand = new RelayCommand(() => SelectedPokemon = null);
    }

    public override string Title => "Trade Room";
    private ActiveTradeRoomContext? Context => _coordinator?.Context;
    public PublicRoomPreview? DemoRoom { get; }
    public string RoomName => IsDemoPreview ? DemoRoom!.RoomName : Context?.Room.Name ?? "Trade Room";
    public string RoomCode => IsDemoPreview ? "PREVIEW" : Context?.Room.RoomCode ?? "";
    public string VisibilityLabel => IsDemoPreview ? "Demo Preview" : "Private";
    public bool IsDemoPreview => DemoRoom is not null;
    public bool IsRealRoom => !IsDemoPreview;
    public bool HasRoomCode => IsRealRoom && !string.IsNullOrWhiteSpace(RoomCode);
    public bool IsOwner => Context?.MembershipRole == RoomMembershipRole.Owner;
    public string MembershipActionText => IsOwner ? "Close Trade Room" : "Leave Trade Room";
    public string YouSummary => IsDemoPreview ? "Sample party" : "Local compatibility connection";
    public string PartnerSummary => IsDemoPreview ? "Sample party" : "Partner presence is not available yet";
    public string MainInstruction => IsDemoPreview
        ? "Preview the connected trading layout"
        : Context?.SwitchRole == SwitchRoomRole.Creator
            ? "Create the room on your Switch"
            : "Find your partner’s room";
    public string InstructionDetails => IsDemoPreview
        ? "All trainers, parties, and connection details on this screen are sample data."
        : Context?.SwitchRole == SwitchRoomRole.Creator
            ? "Open Direct Connection in the game and create a room. Keep it open while SwitchTrade looks for it."
            : "Open room search in Direct Connection and keep the results open while SwitchTrade prepares your partner’s room.";
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The notice is a bindable property of the screen projection.")]
    public string LimitationNotice =>
        "Compatibility mode — shared Ready state, partner presence, and either-trainer room assignment are not live until the authoritative room service is connected.";
    public string ConnectionActionText => _coordinator?.ConnectionState == LegacyConnectionState.Idle
        ? "Connect this Switch"
        : "End connection";
    public string ConnectionStatus => IsDemoPreview
        ? "Sample layout — no remote trainer is connected"
        : _coordinator?.StatusText ?? "Connection not started";
    public bool IsConnectionPending => _coordinator?.IsPending == true;
    public bool HasRecovery => !string.IsNullOrWhiteSpace(_coordinator?.RecoveryMessage);
    public string RecoveryMessage => _coordinator?.RecoveryMessage ?? "";
    public string StageHeading => IsDemoPreview
        ? "Sample party view"
        : _coordinator?.ConnectionState == LegacyConnectionState.Active
            ? "Both Switches are connected"
            : MainInstruction;
    public string LinklineState => IsDemoPreview ? "Sample" : _coordinator?.ConnectionState switch
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
    public PartyPreviewViewData? YouParty { get; }
    public PartyPreviewViewData? PartnerParty { get; }
    public PokemonPreviewViewData? SelectedPokemon
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
    public AsyncCommand LeaveCommand { get; }
    public RelayCommand CopyCodeCommand { get; }
    public RelayCommand CopyInvitationCommand { get; }
    public RelayCommand<PokemonPreviewViewData> SelectPokemonCommand { get; }
    public RelayCommand ClearPokemonCommand { get; }

    private bool CanToggleConnection() => IsServiceReady && _coordinator is { IsPending: false, HasRoom: true };

    private async Task ToggleConnectionAsync()
    {
        if (_coordinator is null) return;
        if (_coordinator.ConnectionState == LegacyConnectionState.Idle)
            await _coordinator.StartConnectionAsync();
        else
            await _coordinator.StopConnectionAsync();
    }

    private async Task LeaveAsync()
    {
        if (await Shell.ConfirmAndReleaseRoomAsync()) Shell.ShowHome();
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
        OnPropertyChanged(nameof(RecoveryMessage));
        OnPropertyChanged(nameof(StageHeading));
        OnPropertyChanged(nameof(LinklineState));
        ConnectionCommand.RaiseCanExecuteChanged();
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
        if (_coordinator is not null) _coordinator.Changed -= CoordinatorChanged;
    }
}
