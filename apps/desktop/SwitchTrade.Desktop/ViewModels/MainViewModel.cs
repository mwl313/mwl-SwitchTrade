using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

public sealed class MainViewModel : ObservableObject, IDisposable
{
    private readonly Stack<ScreenViewModel> _history = new();
    private readonly BackendLauncher _launcher;
    private readonly IDialogService _dialogs;
    private readonly IClipboardService _clipboard;
    private bool _refreshing;
    private ScreenViewModel _currentScreen;
    private bool _isServiceReady;
    private string _readinessText = "Starting SwitchTrade";
    private string _announcement = "";

    internal ControlApiClient Api { get; }
    internal PublicRoomPreviewProvider PreviewProvider { get; }

    public MainViewModel(
        ControlApiClient api,
        BackendLauncher launcher,
        IDialogService dialogs,
        IClipboardService clipboard,
        PublicRoomPreviewProvider previewProvider)
    {
        Api = api;
        _launcher = launcher;
        _dialogs = dialogs;
        _clipboard = clipboard;
        PreviewProvider = previewProvider;
        _currentScreen = new StartupScreenViewModel(this);
        BackCommand = new AsyncCommand(GoBackAsync, () => CanGoBack);
        SettingsCommand = new RelayCommand(OpenSettings);
    }

    public ScreenViewModel CurrentScreen
    {
        get => _currentScreen;
        private set
        {
            if (!Set(ref _currentScreen, value)) return;
            OnPropertyChanged(nameof(CanGoBack));
            BackCommand.RaiseCanExecuteChanged();
        }
    }

    public bool IsServiceReady
    {
        get => _isServiceReady;
        private set
        {
            if (!Set(ref _isServiceReady, value)) return;
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

    public bool CanGoBack => _history.Count > 0 && CurrentScreen is not HomeScreenViewModel;
    public AsyncCommand BackCommand { get; }
    public RelayCommand SettingsCommand { get; }

    public async Task InitializeAsync()
    {
        _history.Clear();
        CurrentScreen = new StartupScreenViewModel(this);
        ReadinessText = "Starting SwitchTrade";

        var status = await Api.TryGetStatusAsync();
        if (status is null)
        {
            _launcher.TryStart();
            for (var attempt = 0; attempt < 8 && status is null; attempt++)
            {
                await Task.Delay(350);
                status = await Api.TryGetStatusAsync();
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
            var status = await Api.TryGetStatusAsync();
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
            "radio_ready" or "session_ready" => "Switch connection active",
            "failed" => "Connection needs attention",
            _ => "Ready",
        };
        if (CurrentScreen is TradeRoomScreenViewModel room) room.ApplyStatus(status);
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
        var settings = new SettingsScreenViewModel(this);
        Navigate(settings);
        _ = settings.LoadAsync();
    }

    public void OpenTradeRoom(TradeRoomInfo room, string internalRole) =>
        Navigate(new TradeRoomScreenViewModel(this, room, internalRole));

    public void OpenDemoRoom(PublicRoomSummary room) =>
        Navigate(new TradeRoomScreenViewModel(this, room));

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
            var message = room.HasActiveConnection
                ? "End the current connection and leave this Trade Room?"
                : "Leave this Trade Room?";
            if (!_dialogs.Confirm("Leave Trade Room", message)) return;
            await room.StopIfNeededAsync();
        }
        CurrentScreen = _history.Pop();
    }

    public bool DismissTemporaryLayer() => CurrentScreen.DismissTemporaryLayer();

    public async Task<bool> CanCloseAsync()
    {
        if (CurrentScreen is not TradeRoomScreenViewModel room || room.IsDemoPreview) return true;
        if (!_dialogs.Confirm("Close SwitchTrade", "End this connection and close SwitchTrade?"))
            return false;
        await room.StopIfNeededAsync();
        return true;
    }

    internal void Copy(string value, string announcement)
    {
        _clipboard.SetText(value);
        Announce(announcement);
    }

    internal void Announce(string message)
    {
        Announcement = "";
        Announcement = message;
    }

    public void Dispose() => Api.Dispose();
}

public sealed class StartupScreenViewModel(MainViewModel shell) : ScreenViewModel(shell)
{
    public override string Title => "Starting SwitchTrade";
}

public sealed class RecoveryScreenViewModel : ScreenViewModel
{
    public RecoveryScreenViewModel(MainViewModel shell) : base(shell)
    {
        RetryCommand = new AsyncCommand(shell.InitializeAsync);
        PreviewCommand = new RelayCommand(shell.OpenPreviewHome);
        SettingsCommand = new RelayCommand(shell.OpenSettings);
    }

    public override string Title => "SwitchTrade couldn’t start";
    public AsyncCommand RetryCommand { get; }
    public RelayCommand PreviewCommand { get; }
    public RelayCommand SettingsCommand { get; }
}

public sealed class HomeScreenViewModel : ScreenViewModel
{
    public HomeScreenViewModel(MainViewModel shell, bool interfacePreview = false) : base(shell)
    {
        IsInterfacePreview = interfacePreview;
        CreateCommand = new RelayCommand(shell.OpenCreate);
        PublicCommand = new RelayCommand(shell.OpenPublicRooms);
        JoinCommand = new RelayCommand(shell.OpenPrivateJoin);
    }

    public override string Title => "Home";
    public bool IsInterfacePreview { get; }
    public bool ShowAttention => !IsServiceReady || IsInterfacePreview;
    public string AttentionText => IsInterfacePreview
        ? "Interface Preview — online actions remain unavailable until the installed SwitchTrade runtime is running."
        : "SwitchTrade needs attention before a private connection can start.";
    public RelayCommand CreateCommand { get; }
    public RelayCommand PublicCommand { get; }
    public RelayCommand JoinCommand { get; }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        OnPropertyChanged(nameof(ShowAttention));
        OnPropertyChanged(nameof(AttentionText));
    }
}

public sealed class CreateTradeRoomScreenViewModel : ScreenViewModel
{
    private string _roomName = "";
    private bool _isPublicPreview;
    private string _trainerName = "";
    private string _gameVersion = "None";
    private string _language = "None";
    private string _offering = "";
    private string _wanted = "";
    private string _note = "";
    private string _errorMessage = "";
    private bool _isBusy;

    public CreateTradeRoomScreenViewModel(MainViewModel shell) : base(shell)
    {
        CreateCommand = new AsyncCommand(CreateAsync, CanCreate);
    }

    public override string Title => "Create a Trade Room";
    public IReadOnlyList<string> GameVersions { get; } = ["None", "FireRed", "LeafGreen"];
    public IReadOnlyList<string> Languages { get; } = ["None", "English", "Japanese", "French", "German", "Italian", "Spanish"];

    public string RoomName
    {
        get => _roomName;
        set { if (Set(ref _roomName, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public bool IsPrivateRoom
    {
        get => !IsPublicPreview;
        set { if (value) SetPublicPreview(false); }
    }
    public bool IsPublicPreview
    {
        get => _isPublicPreview;
        set { if (value) SetPublicPreview(true); }
    }
    public string SubmitText => IsPublicPreview ? "Preview Trade Room" : "Create Trade Room";
    public string TrainerName
    {
        get => _trainerName;
        set { if (Set(ref _trainerName, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public string GameVersion
    {
        get => _gameVersion;
        set { if (Set(ref _gameVersion, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public string Language
    {
        get => _language;
        set { if (Set(ref _language, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public string Offering { get => _offering; set => Set(ref _offering, value); }
    public string Wanted { get => _wanted; set => Set(ref _wanted, value); }
    public string Note { get => _note; set => Set(ref _note, value); }
    public string ErrorMessage { get => _errorMessage; private set => Set(ref _errorMessage, value); }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public bool IsBusy { get => _isBusy; private set => Set(ref _isBusy, value); }
    public AsyncCommand CreateCommand { get; }

    internal static bool RequiredFieldsComplete(string roomName, string trainerName, string game, string language) =>
        roomName.Trim().Length is >= 1 and <= 22 &&
        trainerName.Trim().Length is >= 1 and <= 20 &&
        game != "None" && language != "None";

    private bool CanCreate() => !IsBusy &&
                                RequiredFieldsComplete(RoomName, TrainerName, GameVersion, Language) &&
                                (IsPublicPreview || IsServiceReady);

    private void SetPublicPreview(bool value)
    {
        if (_isPublicPreview == value) return;
        _isPublicPreview = value;
        OnPropertyChanged(nameof(IsPublicPreview));
        OnPropertyChanged(nameof(IsPrivateRoom));
        OnPropertyChanged(nameof(SubmitText));
        CreateCommand.RaiseCanExecuteChanged();
    }

    private async Task CreateAsync()
    {
        ErrorMessage = "";
        OnPropertyChanged(nameof(HasError));
        if (IsPublicPreview)
        {
            Shell.OpenDemoRoom(new PublicRoomSummary(
                "custom-preview", RoomName.Trim(), TrainerName.Trim(),
                GameVersion, Language, string.IsNullOrWhiteSpace(Offering) ? "Not specified" : Offering.Trim(),
                string.IsNullOrWhiteSpace(Wanted) ? "Anything" : Wanted.Trim(), "Not shared", "Preview",
                64, DateTimeOffset.UtcNow, Note.Trim()));
            return;
        }
        try
        {
            IsBusy = true;
            var room = await Shell.Api.CreateTradeRoomAsync(RoomName.Trim(), "private");
            Shell.OpenTradeRoom(room, "host");
        }
        catch (UserFacingException error)
        {
            ErrorMessage = error.UserMessage;
            OnPropertyChanged(nameof(HasError));
        }
        finally
        {
            IsBusy = false;
            CreateCommand.RaiseCanExecuteChanged();
        }
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        CreateCommand.RaiseCanExecuteChanged();
    }
}

public sealed class JoinPrivateRoomScreenViewModel : ScreenViewModel
{
    private string _roomCode = "";
    private string _errorMessage = "";
    private TradeRoomInfo? _resolvedRoom;

    public JoinPrivateRoomScreenViewModel(MainViewModel shell) : base(shell)
    {
        FindCommand = new AsyncCommand(FindAsync, CanFind);
        JoinCommand = new RelayCommand(Join, () => ResolvedRoom is not null);
    }

    public override string Title => "Join a private Trade Room";
    public string RoomCode
    {
        get => _roomCode;
        set
        {
            var normalized = NormalizeCode(value);
            if (!Set(ref _roomCode, normalized)) return;
            ResolvedRoom = null;
            ErrorMessage = "";
            FindCommand.RaiseCanExecuteChanged();
        }
    }
    public string ErrorMessage
    {
        get => _errorMessage;
        private set { if (Set(ref _errorMessage, value)) OnPropertyChanged(nameof(HasError)); }
    }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public TradeRoomInfo? ResolvedRoom
    {
        get => _resolvedRoom;
        private set
        {
            if (!Set(ref _resolvedRoom, value)) return;
            OnPropertyChanged(nameof(HasResolvedRoom));
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public bool HasResolvedRoom => ResolvedRoom is not null;
    public AsyncCommand FindCommand { get; }
    public RelayCommand JoinCommand { get; }

    public static string NormalizeCode(string value) =>
        new(value.Where(char.IsLetterOrDigit).Take(8).Select(char.ToUpperInvariant).ToArray());

    private bool CanFind() => IsServiceReady && RoomCode.Length is >= 4 and <= 8;

    private async Task FindAsync()
    {
        ErrorMessage = "";
        try { ResolvedRoom = await Shell.Api.JoinTradeRoomAsync(RoomCode); }
        catch (UserFacingException error) { ErrorMessage = error.UserMessage; }
    }

    private void Join()
    {
        if (ResolvedRoom is not null) Shell.OpenTradeRoom(ResolvedRoom, "guest");
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        FindCommand.RaiseCanExecuteChanged();
    }
}

public sealed class PublicRoomsScreenViewModel : ScreenViewModel
{
    private readonly IReadOnlyList<PublicRoomSummary> _allRooms;
    private string _searchText = "";
    private string _searchBy = "Any field";
    private string _availability = "Open only";
    private string _game = "Any game";
    private string _language = "Any language";
    private string _sort = "Best match";
    private PublicRoomSummary? _selectedRoom;

    public PublicRoomsScreenViewModel(MainViewModel shell) : base(shell)
    {
        _allRooms = shell.PreviewProvider.GetRooms();
        PreviewCommand = new RelayCommand(Preview, () => SelectedRoom is not null);
        ClearFiltersCommand = new RelayCommand(ClearFilters);
        RefreshCommand = new RelayCommand(ApplyFilters);
        ApplyFilters();
    }

    public override string Title => "Browse Public Rooms";
    public ObservableCollection<PublicRoomSummary> Rooms { get; } = [];
    public IReadOnlyList<string> SearchByOptions { get; } = ["Any field", "Room name", "Trainer", "Pokémon offered", "Pokémon wanted"];
    public IReadOnlyList<string> AvailabilityOptions { get; } = ["Open only", "All rooms"];
    public IReadOnlyList<string> GameOptions { get; } = ["Any game", "FireRed", "LeafGreen"];
    public IReadOnlyList<string> LanguageOptions { get; } = ["Any language", "English", "Japanese", "French"];
    public IReadOnlyList<string> SortOptions { get; } = ["Best match", "Lowest latency", "Recently opened"];
    public string SearchText { get => _searchText; set { if (Set(ref _searchText, value)) ApplyFilters(); } }
    public string SearchBy { get => _searchBy; set { if (Set(ref _searchBy, value)) ApplyFilters(); } }
    public string Availability { get => _availability; set { if (Set(ref _availability, value)) ApplyFilters(); } }
    public string Game { get => _game; set { if (Set(ref _game, value)) ApplyFilters(); } }
    public string Language { get => _language; set { if (Set(ref _language, value)) ApplyFilters(); } }
    public string Sort { get => _sort; set { if (Set(ref _sort, value)) ApplyFilters(); } }
    public PublicRoomSummary? SelectedRoom
    {
        get => _selectedRoom;
        set
        {
            if (!Set(ref _selectedRoom, value)) return;
            OnPropertyChanged(nameof(HasSelection));
            PreviewCommand.RaiseCanExecuteChanged();
        }
    }
    public bool HasSelection => SelectedRoom is not null;
    public bool HasRooms => Rooms.Count > 0;
    public RelayCommand PreviewCommand { get; }
    public RelayCommand ClearFiltersCommand { get; }
    public RelayCommand RefreshCommand { get; }

    private void ApplyFilters()
    {
        IEnumerable<PublicRoomSummary> query = _allRooms;
        if (Availability == "Open only") query = query.Where(room => room.Availability == "Open");
        if (Game != "Any game") query = query.Where(room => room.GameVersion == Game);
        if (Language != "Any language") query = query.Where(room => room.Language == Language);
        if (!string.IsNullOrWhiteSpace(SearchText))
        {
            var text = SearchText.Trim();
            query = query.Where(room => SearchBy switch
            {
                "Room name" => Contains(room.RoomName, text),
                "Trainer" => Contains(room.TrainerDisplayName, text),
                "Pokémon offered" => Contains(room.Offering, text),
                "Pokémon wanted" => Contains(room.Wanted, text),
                _ => Contains(room.RoomName, text) || Contains(room.TrainerDisplayName, text) ||
                     Contains(room.Offering, text) || Contains(room.Wanted, text),
            });
        }
        query = Sort switch
        {
            "Lowest latency" => query.OrderBy(room => room.LatencyMs),
            "Recently opened" => query.OrderByDescending(room => room.CreatedAt),
            _ => query.OrderBy(room => room.Availability != "Open").ThenBy(room => room.LatencyMs),
        };
        Rooms.Clear();
        foreach (var room in query) Rooms.Add(room);
        SelectedRoom = Rooms.FirstOrDefault();
        OnPropertyChanged(nameof(HasRooms));
    }

    private static bool Contains(string value, string text) =>
        value.Contains(text, StringComparison.CurrentCultureIgnoreCase);

    private void ClearFilters()
    {
        _searchText = "";
        _availability = "Open only";
        _game = "Any game";
        _language = "Any language";
        OnPropertyChanged(nameof(SearchText));
        OnPropertyChanged(nameof(Availability));
        OnPropertyChanged(nameof(Game));
        OnPropertyChanged(nameof(Language));
        ApplyFilters();
    }

    private void Preview()
    {
        if (SelectedRoom is not null) Shell.OpenDemoRoom(SelectedRoom);
    }

    public override bool DismissTemporaryLayer()
    {
        if (SelectedRoom is null) return false;
        SelectedRoom = null;
        return true;
    }
}

public sealed class SettingsScreenViewModel : ScreenViewModel
{
    private string _statusMessage = "";

    public SettingsScreenViewModel(MainViewModel shell) : base(shell)
    {
        RecheckCommand = new AsyncCommand(LoadAsync);
        SupportCommand = new AsyncCommand(CreateSupportAsync, () => IsServiceReady);
    }

    public override string Title => "Settings";
    public ObservableCollection<AdapterProfileViewData> Adapters { get; } = [];
    public string StatusMessage { get => _statusMessage; private set => Set(ref _statusMessage, value); }
    public AsyncCommand RecheckCommand { get; }
    public AsyncCommand SupportCommand { get; }

    public async Task LoadAsync()
    {
        Adapters.Clear();
        if (!IsServiceReady)
        {
            StatusMessage = "Connect the installed SwitchTrade runtime to check Wi-Fi adapters.";
            return;
        }
        try
        {
            foreach (var adapter in await Shell.Api.GetAdapterProfilesAsync()) Adapters.Add(adapter);
            StatusMessage = "These are compatibility profiles. Live device selection and repair are not available yet.";
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private async Task CreateSupportAsync()
    {
        try
        {
            await Shell.Api.CreateSupportBundleAsync();
            StatusMessage = "Support file created successfully.";
            Shell.Announce(StatusMessage);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        SupportCommand.RaiseCanExecuteChanged();
    }
}

public sealed class TradeRoomScreenViewModel : ScreenViewModel
{
    private readonly string? _internalRole;
    private bool _hasActiveConnection;
    private string _connectionStatus;
    private PokemonViewData? _selectedPokemon;

    public TradeRoomScreenViewModel(MainViewModel shell, TradeRoomInfo room, string internalRole) : base(shell)
    {
        RoomName = room.Name;
        RoomCode = room.RoomCode;
        VisibilityLabel = room.Visibility == "public" ? "Public" : "Private";
        _internalRole = internalRole;
        _connectionStatus = "Connection not started";
        ConnectionCommand = new AsyncCommand(ToggleConnectionAsync, () => IsServiceReady);
        CopyCodeCommand = new RelayCommand(() => Shell.Copy(RoomCode, "Room code copied"));
        CopyInvitationCommand = new RelayCommand(() => Shell.Copy(
            $"Join my SwitchTrade room “{RoomName}” with code {RoomCode}.", "Invitation copied"));
        SelectPokemonCommand = new RelayCommand<PokemonViewData>(pokemon => SelectedPokemon = pokemon,
            pokemon => pokemon is not null && !pokemon.IsEmpty);
    }

    public TradeRoomScreenViewModel(MainViewModel shell, PublicRoomSummary preview) : base(shell)
    {
        RoomName = preview.RoomName;
        RoomCode = "PREVIEW";
        VisibilityLabel = "Demo Preview";
        IsDemoPreview = true;
        _connectionStatus = "Sample layout — no remote trainer is connected";
        var parties = shell.PreviewProvider.GetSampleParties();
        YouParty = parties.You;
        PartnerParty = parties.Partner;
        ConnectionCommand = new AsyncCommand(() => Task.CompletedTask, () => false);
        CopyCodeCommand = new RelayCommand(() => { }, () => false);
        CopyInvitationCommand = new RelayCommand(() => { }, () => false);
        SelectPokemonCommand = new RelayCommand<PokemonViewData>(pokemon => SelectedPokemon = pokemon,
            pokemon => pokemon is not null && !pokemon.IsEmpty);
    }

    public override string Title => "Trade Room";
    public string RoomName { get; }
    public string RoomCode { get; }
    public string VisibilityLabel { get; }
    public bool IsDemoPreview { get; }
    public bool IsRealRoom => !IsDemoPreview;
    public bool HasRoomCode => IsRealRoom && !string.IsNullOrWhiteSpace(RoomCode);
    public string YouSummary => IsDemoPreview ? "Sample party" : "This app";
    public string PartnerSummary => IsDemoPreview ? "Sample party" : "Shared status unavailable in current private beta";
    public string MainInstruction => IsDemoPreview
        ? "Preview the connected trading layout"
        : _internalRole == "host" ? "Create the room on your Switch" : "Find your partner’s room";
    public string InstructionDetails => IsDemoPreview
        ? "All trainers, parties, and connection details on this screen are sample data."
        : _internalRole == "host"
            ? "Open Direct Connection in the game and create a room. Keep that room open while SwitchTrade looks for it."
            : "Open the room search in Direct Connection and keep the results screen open. SwitchTrade will mirror your partner’s room nearby.";
    public string LimitationNotice =>
        "Current private beta: shared Ready status and choosing either room creator require the authoritative room service and are not shown as live features yet.";
    public bool HasActiveConnection
    {
        get => _hasActiveConnection;
        private set
        {
            if (!Set(ref _hasActiveConnection, value)) return;
            OnPropertyChanged(nameof(ConnectionActionText));
        }
    }
    public string ConnectionActionText => HasActiveConnection ? "End connection" : "Connect this Switch";
    public string ConnectionStatus { get => _connectionStatus; private set => Set(ref _connectionStatus, value); }
    public PartyPanelViewData? YouParty { get; }
    public PartyPanelViewData? PartnerParty { get; }
    public PokemonViewData? SelectedPokemon
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
    public RelayCommand CopyCodeCommand { get; }
    public RelayCommand CopyInvitationCommand { get; }
    public RelayCommand<PokemonViewData> SelectPokemonCommand { get; }

    private async Task ToggleConnectionAsync()
    {
        if (_internalRole is null) return;
        try
        {
            if (HasActiveConnection)
            {
                await Shell.Api.StopConnectionAsync();
                HasActiveConnection = false;
                ConnectionStatus = "Connection ended";
            }
            else
            {
                await Shell.Api.StartConnectionAsync(_internalRole, RoomCode);
                HasActiveConnection = true;
                ConnectionStatus = "Preparing the connection. Follow the Switch instructions above.";
            }
        }
        catch (UserFacingException error) { ConnectionStatus = error.UserMessage; }
    }

    public void ApplyStatus(ControlStatus status)
    {
        if (!HasActiveConnection) return;
        ConnectionStatus = status.Status switch
        {
            "initializing" or "starting" => "Preparing the connection",
            "relay_connected" => "Waiting for the room on the creator’s Switch",
            "radio_ready" => "The local Switch connection is ready",
            "session_ready" => "SwitchTrade is carrying the game connection",
            "failed" => "This connection needs attention. End it, check Settings, and try again.",
            "completed" => "Connection ended",
            _ => ConnectionStatus,
        };
        if (status.Status is "failed" or "completed") HasActiveConnection = false;
    }

    public async Task StopIfNeededAsync()
    {
        if (!HasActiveConnection) return;
        try { await Shell.Api.StopConnectionAsync(); }
        catch (UserFacingException) { }
        HasActiveConnection = false;
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
}
