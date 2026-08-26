using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;
using SwitchTrade.Desktop.State;

namespace SwitchTrade.Desktop.ViewModels;

public sealed class MainViewModel : ObservableObject, IDisposable
{
    private readonly Stack<ScreenViewModel> _history = new();
    private readonly BackendLauncher _launcher;
    private readonly IDialogService _dialogs;
    private readonly IClipboardService _clipboard;
    private CancellationTokenSource? _startupCancellation;
    private bool _refreshing;
    private ScreenViewModel _currentScreen;
    private TradeRoomScreenViewModel? _activeTradeRoom;
    private bool _isServiceReady;
    private bool _isPublicDirectoryAvailable;
    private string _readinessText = "Starting SwitchTrade";
    private string _announcement = "";
    private string _controlStateText = "Checking";
    private string _relayStateText = "Not checked";
    private string _radioStateText = "Not checked";
    private string _sessionStateText = "Not active";
    private string _recoverySummary = "The installed local service did not respond.";
    private string _recoveryInstructions = "Close SwitchTrade, run the latest signed SwitchTradeSetup.exe, and choose Repair. Do not reset or unregister WSL.";
    private string _recoveryStage = "control";
    private string _recoveryTechnicalDetails = "Local setup · The desktop app could not reach 127.0.0.1:8787.";

    internal IControlGateway Gateway { get; }
    internal ActiveTradeRoomCoordinator RoomCoordinator { get; }

    public MainViewModel(
        IControlGateway gateway,
        BackendLauncher launcher,
        IDialogService dialogs,
        IClipboardService clipboard)
    {
        Gateway = gateway;
        _launcher = launcher;
        _dialogs = dialogs;
        _clipboard = clipboard;
        RoomCoordinator = new ActiveTradeRoomCoordinator(gateway);
        _currentScreen = new StartupScreenViewModel(this);
        BackCommand = new AsyncCommand(GoBackAsync, () => CanGoBack);
        SettingsCommand = new RelayCommand(OpenSettings);
    }

    public ScreenViewModel CurrentScreen
    {
        get => _currentScreen;
        private set
        {
            if (ReferenceEquals(_currentScreen, value)) return;
            _currentScreen.OnNavigatedFrom();
            if (!Set(ref _currentScreen, value)) return;
            _ = value.OnNavigatedToAsync();
            OnPropertyChanged(nameof(CanGoBack));
            BackCommand.RaiseCanExecuteChanged();
            Announce(value.Title);
        }
    }

    public bool IsServiceReady
    {
        get => _isServiceReady;
        private set
        {
            if (!Set(ref _isServiceReady, value)) return;
            CurrentScreen.NotifyShellState();
            _activeTradeRoom?.NotifyShellState();
        }
    }

    public bool IsPublicDirectoryAvailable
    {
        get => _isPublicDirectoryAvailable;
        private set
        {
            if (!Set(ref _isPublicDirectoryAvailable, value)) return;
            CurrentScreen.NotifyShellState();
        }
    }

    public string ReadinessText
    {
        get => _readinessText;
        private set => Set(ref _readinessText, value);
    }

    public string Announcement
    {
        get => _announcement;
        private set => Set(ref _announcement, value);
    }

    public string ControlStateText { get => _controlStateText; private set => Set(ref _controlStateText, value); }
    public string RelayStateText { get => _relayStateText; private set => Set(ref _relayStateText, value); }
    public string RadioStateText { get => _radioStateText; private set => Set(ref _radioStateText, value); }
    public string SessionStateText { get => _sessionStateText; private set => Set(ref _sessionStateText, value); }
    public string RecoverySummary { get => _recoverySummary; private set => Set(ref _recoverySummary, value); }
    public string RecoveryInstructions { get => _recoveryInstructions; private set => Set(ref _recoveryInstructions, value); }
    public string RecoveryStage { get => _recoveryStage; private set => Set(ref _recoveryStage, value); }
    public string RecoveryTechnicalDetails
    {
        get => _recoveryTechnicalDetails;
        private set => Set(ref _recoveryTechnicalDetails, value);
    }

    public bool CanGoBack => _history.Count > 0 && CurrentScreen is not HomeScreenViewModel;
    public AsyncCommand BackCommand { get; }
    public RelayCommand SettingsCommand { get; }

    public async Task InitializeAsync()
    {
        _startupCancellation?.Cancel();
        _startupCancellation?.Dispose();
        _startupCancellation = new CancellationTokenSource();
        var cancellationToken = _startupCancellation.Token;

        try
        {
            await InitializeCoreAsync(cancellationToken);
        }
        catch (OperationCanceledException) when (cancellationToken.IsCancellationRequested)
        {
            // A retry or application shutdown superseded this startup attempt.
        }
    }

    private async Task InitializeCoreAsync(CancellationToken cancellationToken)
    {

        _history.Clear();
        CurrentScreen = new StartupScreenViewModel(this);
        ReadinessText = "Starting SwitchTrade";

        var status = await Gateway.TryGetStatusAsync(cancellationToken);
        if (status is null)
        {
            _launcher.TryStart();
            for (var attempt = 0; attempt < 8 && status is null; attempt++)
            {
                await Task.Delay(350, cancellationToken);
                status = await Gateway.TryGetStatusAsync(cancellationToken);
            }
        }

        if (status is not null)
        {
            ApplyStatus(status);
            await RefreshPartiesAsync(cancellationToken);
            if (IsServiceReady) ShowHome();
            else CurrentScreen = new RecoveryScreenViewModel(this);
            return;
        }

        IsServiceReady = false;
        IsPublicDirectoryAvailable = false;
        ReadinessText = "Setup needs attention";
        ControlStateText = "Unavailable";
        RecoverySummary = "The installed local service did not respond.";
        RecoveryStage = "control";
        RecoveryInstructions = "Close SwitchTrade, run the latest signed SwitchTradeSetup.exe, and choose Repair. Do not reset or unregister WSL.";
        RecoveryTechnicalDetails = "control.unavailable · 127.0.0.1:8787 did not answer the bounded readiness probe.";
        CurrentScreen = new RecoveryScreenViewModel(this);
    }

    public async Task RefreshAsync()
    {
        if (_refreshing) return;
        _refreshing = true;
        try
        {
            var status = await Gateway.TryGetStatusAsync();
            if (status is null)
            {
                IsServiceReady = false;
                IsPublicDirectoryAvailable = false;
                ReadinessText = "Setup needs attention";
                RecoveryStage = "control";
                RecoverySummary = "The installed local service did not respond.";
                RecoveryInstructions = "Close SwitchTrade, run the latest signed SwitchTradeSetup.exe, and choose Repair. Do not reset or unregister WSL.";
                if (CurrentScreen is RecoveryScreenViewModel unavailableRecovery) unavailableRecovery.NotifyRecoveryChanged();
                return;
            }
            ApplyStatus(status);
            if (_activeTradeRoom is not null)
            {
                var room = await Gateway.TryGetTradeRoomAsync();
                if (room is not null) RoomCoordinator.ApplyRoom(room);
            }
            await RefreshPartiesAsync();
        }
        finally { _refreshing = false; }
    }

    private void ApplyStatus(ControlStatus status)
    {
        var control = status.Axis("control");
        ControlStateText = control.Display;
        RelayStateText = status.Axis("relay").Display;
        RadioStateText = status.Axis("radio").Display;
        SessionStateText = status.Axis("session").Display;
        IsServiceReady = status.Compatible && control.Status == "ready";
        IsPublicDirectoryAvailable = IsServiceReady && status.HasCapability("public-directory.v1");
        ReadinessText = !status.Compatible ? "Update or repair required" : status.Status switch
        {
            "initializing" or "starting" => "Preparing connection",
            "relay_connected" => "Connected online",
            "radio_ready" or "session_ready" => "Connection active",
            "failed" => "Connection needs attention",
            _ => "Ready",
        };
        RecoverySummary = !status.Compatible
            ? "The desktop app and installed SwitchTrade runtime are not compatible."
            : status.Error ?? "The installed runtime needs attention.";
        RecoveryTechnicalDetails = !status.Compatible
            ? $"app.version_mismatch · UI expects {ControlApiClient.ReadinessContract} / 0.2.x; runtime reported {status.ContractVersion} / {status.Version}."
            : $"{status.FailureStage ?? "control"}.failed · run {status.RunId} · action {status.RecoveryAction ?? "retry"}";
        RecoveryStage = !status.Compatible ? "version" : status.FailureStage ?? "control";
        RecoveryInstructions = RecoveryStage switch
        {
            "version" => "Close SwitchTrade and run a newer SwitchTrade Setup package with Update.",
            "relay" => "Check this PC’s internet connection, then try again. If the relay still fails, export a support bundle before changing WSL.",
            "radio" => "Open Settings → Connection, select the adapter, and run the adapter check. Reattach USB only when the diagnostic asks.",
            "session" => "End the failed connection and try once more. If it repeats, export a support bundle before creating another room.",
            "decoder" => "End the current connection and try again. Trading remains blocked until the installed decoder matches this app.",
            _ => "Close SwitchTrade, run the latest signed SwitchTradeSetup.exe, and choose Repair. Do not reset or unregister WSL.",
        };
        if (CurrentScreen is RecoveryScreenViewModel recovery) recovery.NotifyRecoveryChanged();
        RoomCoordinator.ApplyStatus(status);
    }

    private async Task RefreshPartiesAsync(CancellationToken cancellationToken = default)
    {
        if (_activeTradeRoom is null) return;
        var parties = await Gateway.TryGetPartiesAsync(cancellationToken);
        if (parties is not null) _activeTradeRoom.ApplyLiveParties(parties);
    }

    public void ShowHome()
    {
        _history.Clear();
        CurrentScreen = new HomeScreenViewModel(this);
    }

    public void OpenCreate() => Navigate(new CreateTradeRoomScreenViewModel(this));
    public void OpenPrivateJoin() => Navigate(new JoinPrivateRoomScreenViewModel(this));
    public void OpenPublicRooms() => Navigate(new PublicRoomsScreenViewModel(this));

    public void OpenSettings()
    {
        if (CurrentScreen is SettingsScreenViewModel) return;
        Navigate(new SettingsScreenViewModel(this));
    }

    public void OpenTradeRoom(
        TradeRoomInfo room,
        RoomMembershipRole membershipRole,
        SwitchRoomRole switchRole,
        TradeRoomCreateRequest? invitation = null)
    {
        RoomCoordinator.Open(room, membershipRole, switchRole, invitation);
        _activeTradeRoom?.Dispose();
        _activeTradeRoom = new TradeRoomScreenViewModel(this, RoomCoordinator);
        Navigate(_activeTradeRoom);
    }

    private void Navigate(ScreenViewModel screen)
    {
        _history.Push(CurrentScreen);
        CurrentScreen = screen;
    }

    public async Task GoBackAsync()
    {
        if (!CanGoBack) return;
        if (CurrentScreen is TradeRoomScreenViewModel)
        {
            if (!await ConfirmAndReleaseRoomAsync()) return;
            _history.Clear();
            CurrentScreen = new HomeScreenViewModel(this);
            return;
        }
        CurrentScreen = _history.Pop();
    }

    public bool DismissTemporaryLayer() => CurrentScreen.DismissTemporaryLayer();

    public async Task<bool> CanCloseAsync()
    {
        if (!RoomCoordinator.HasRoom) return true;
        if (_dialogs.Show(ReleaseDialog()) != DialogChoice.Primary) return false;
        if (await RoomCoordinator.ReleaseRoomAsync()) return true;

        var retry = _dialogs.Show(new DialogRequest(
            "SwitchTrade couldn’t finish closing",
            $"{RoomCoordinator.StatusText} {RoomCoordinator.RecoveryMessage} You can try again or close the app anyway. " +
            "If you close anyway, your place may remain reserved until the online room expires.",
            "Try again",
            "Keep SwitchTrade open",
            "Close anyway"));
        if (retry == DialogChoice.Primary) return await RoomCoordinator.ReleaseRoomAsync();
        if (retry != DialogChoice.Secondary) return false;
        RoomCoordinator.ForceClear();
        return true;
    }

    internal async Task<bool> ConfirmAndReleaseRoomAsync()
    {
        if (_dialogs.Show(ReleaseDialog()) != DialogChoice.Primary) return false;
        if (await RoomCoordinator.ReleaseRoomAsync())
        {
            _activeTradeRoom?.Dispose();
            _activeTradeRoom = null;
            return true;
        }
        Announce(RoomCoordinator.StatusText);
        return false;
    }

    private DialogRequest ReleaseDialog()
    {
        var owner = RoomCoordinator.Context?.MembershipRole == RoomMembershipRole.Owner;
        return owner
            ? new DialogRequest(
                "Close Trade Room",
                "Close this Trade Room for both trainers? This cannot be undone.",
                "Close Trade Room", IsDestructive: true)
            : new DialogRequest(
                "Leave Trade Room",
                "Leave this Trade Room? Your partner will remain in the room.",
                "Leave Trade Room", IsDestructive: true);
    }

    internal void Copy(string value, string announcement)
    {
        Announce(_clipboard.TrySetText(value) ? announcement : "SwitchTrade couldn’t copy that text.");
    }

    internal string ReadClipboard() => _clipboard.TryGetText(out var text) ? text : "";

    internal async Task<bool> RepairAdapterAsync()
    {
        try
        {
            await Gateway.RepairAdapterAsync();
            Announce("The adapter health check passed. End the failed connection and try again.");
            await RefreshAsync();
            return true;
        }
        catch (UserFacingException error)
        {
            Announce(error.UserMessage);
            return false;
        }
    }

    internal void Announce(string message)
    {
        Announcement = "";
        Announcement = message;
    }

    public void Dispose()
    {
        _startupCancellation?.Cancel();
        _startupCancellation?.Dispose();
        _activeTradeRoom?.Dispose();
        Gateway.Dispose();
    }
}
