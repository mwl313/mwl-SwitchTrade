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
    private string _readinessText = "Starting SwitchTrade";
    private string _announcement = "";

    internal IControlGateway Gateway { get; }
    internal PublicRoomPreviewProvider PreviewProvider { get; }
    internal ActiveTradeRoomCoordinator RoomCoordinator { get; }

    public MainViewModel(
        IControlGateway gateway,
        BackendLauncher launcher,
        IDialogService dialogs,
        IClipboardService clipboard,
        PublicRoomPreviewProvider previewProvider)
    {
        Gateway = gateway;
        _launcher = launcher;
        _dialogs = dialogs;
        _clipboard = clipboard;
        PreviewProvider = previewProvider;
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
            ShowHome();
            return;
        }

        IsServiceReady = false;
        ReadinessText = "Setup needs attention";
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
                ReadinessText = "Setup needs attention";
                return;
            }
            ApplyStatus(status);
        }
        finally { _refreshing = false; }
    }

    private void ApplyStatus(ControlStatus status)
    {
        IsServiceReady = true;
        ReadinessText = status.Status switch
        {
            "initializing" or "starting" => "Preparing connection",
            "relay_connected" => "Connected online",
            "radio_ready" or "session_ready" => "Connection active",
            "failed" => "Connection needs attention",
            _ => "Ready",
        };
        RoomCoordinator.ApplyStatus(status);
    }

    public void ShowHome()
    {
        _history.Clear();
        CurrentScreen = new HomeScreenViewModel(this);
    }

    public void OpenPreviewHome()
    {
        _history.Clear();
        CurrentScreen = new HomeScreenViewModel(this, true);
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

    public void OpenDemoRoom(PublicRoomPreview room) => Navigate(new TradeRoomScreenViewModel(this, room));

    private void Navigate(ScreenViewModel screen)
    {
        _history.Push(CurrentScreen);
        CurrentScreen = screen;
    }

    public async Task GoBackAsync()
    {
        if (!CanGoBack) return;
        if (CurrentScreen is TradeRoomScreenViewModel room && !room.IsDemoPreview)
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
