using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "The navigation lifecycle cancels and replaces the request token source.")]
public sealed class CreateTradeRoomScreenViewModel : ScreenViewModel
{
    private CancellationTokenSource _requestCancellation = new();
    private string _roomName = "";
    private bool _isPublicPreview;
    private string _trainerName = "";
    private GameVersionChoice _gameVersion;
    private GameLanguage _language;
    private string _offering = "";
    private string _wanted = "";
    private string _note = "";
    private string _errorMessage = "";
    private bool _isBusy;

    public CreateTradeRoomScreenViewModel(MainViewModel shell) : base(shell) =>
        CreateCommand = new AsyncCommand(CreateAsync, CanCreate);

    public override string Title => "Create a Trade Room";
    public IReadOnlyList<SelectionOption<GameVersionChoice>> GameVersions { get; } =
    [
        new(GameVersionChoice.None, "None"),
        new(GameVersionChoice.FireRed, "FireRed"),
        new(GameVersionChoice.LeafGreen, "LeafGreen"),
    ];
    public IReadOnlyList<SelectionOption<GameLanguage>> Languages { get; } =
    [
        new(GameLanguage.None, "None"), new(GameLanguage.English, "English"),
        new(GameLanguage.Japanese, "Japanese"), new(GameLanguage.French, "French"),
        new(GameLanguage.German, "German"), new(GameLanguage.Italian, "Italian"),
        new(GameLanguage.Spanish, "Spanish"),
    ];

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
    public GameVersionChoice GameVersion
    {
        get => _gameVersion;
        set { if (Set(ref _gameVersion, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public GameLanguage Language
    {
        get => _language;
        set { if (Set(ref _language, value)) CreateCommand.RaiseCanExecuteChanged(); }
    }
    public string Offering { get => _offering; set => Set(ref _offering, value); }
    public string Wanted { get => _wanted; set => Set(ref _wanted, value); }
    public string Note { get => _note; set => Set(ref _note, value); }
    public string ErrorMessage
    {
        get => _errorMessage;
        private set { if (Set(ref _errorMessage, value)) OnPropertyChanged(nameof(HasError)); }
    }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (!Set(ref _isBusy, value)) return;
            CreateCommand.RaiseCanExecuteChanged();
        }
    }
    public AsyncCommand CreateCommand { get; }

    internal static bool RequiredFieldsComplete(
        string roomName, string trainerName, GameVersionChoice game, GameLanguage language) =>
        roomName.Trim().Length is >= 1 and <= 22 &&
        trainerName.Trim().Length is >= 1 and <= 20 &&
        game != GameVersionChoice.None && language != GameLanguage.None;

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
        var request = new TradeRoomCreateRequest(
            RoomName.Trim(), TrainerName.Trim(), GameVersion, Language,
            Offering.Trim(), Wanted.Trim(), Note.Trim());
        if (IsPublicPreview)
        {
            Shell.OpenDemoRoom(new PublicRoomPreview(
                "custom-preview", request.RoomName, request.TrainerDisplayName, request.Game,
                request.Language, string.IsNullOrWhiteSpace(request.Offering) ? "Not specified" : request.Offering,
                string.IsNullOrWhiteSpace(request.Wanted) ? "Anything" : request.Wanted,
                "Not shared", PreviewAvailability.Open, 64, DateTimeOffset.UtcNow, request.Note));
            return;
        }

        try
        {
            IsBusy = true;
            var room = await Shell.Gateway.CreateTradeRoomAsync(request, _requestCancellation.Token);
            if (!ReferenceEquals(Shell.CurrentScreen, this)) return;
            Shell.OpenTradeRoom(room, RoomMembershipRole.Owner, SwitchRoomRole.Unassigned, request);
        }
        catch (OperationCanceledException) when (_requestCancellation.IsCancellationRequested) { }
        catch (UserFacingException error) { ErrorMessage = error.UserMessage; }
        finally { IsBusy = false; }
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        CreateCommand.RaiseCanExecuteChanged();
    }

    public override Task OnNavigatedToAsync()
    {
        if (_requestCancellation.IsCancellationRequested)
        {
            _requestCancellation.Dispose();
            _requestCancellation = new CancellationTokenSource();
        }
        return Task.CompletedTask;
    }

    public override void OnNavigatedFrom() => _requestCancellation.Cancel();
}

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "The navigation lifecycle cancels and replaces the request token source.")]
public sealed class JoinPrivateRoomScreenViewModel : ScreenViewModel
{
    private CancellationTokenSource _requestCancellation = new();
    private string _roomCode = "";
    private string _errorMessage = "";
    private bool _isBusy;

    public JoinPrivateRoomScreenViewModel(MainViewModel shell) : base(shell)
    {
        JoinCommand = new AsyncCommand(JoinAsync, CanJoin);
        PasteCommand = new RelayCommand(Paste);
    }

    public override string Title => "Join a Private Room";
    public string RoomCode
    {
        get => _roomCode;
        set
        {
            var normalized = NormalizeCode(value);
            if (!Set(ref _roomCode, normalized)) return;
            ErrorMessage = "";
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public string ErrorMessage
    {
        get => _errorMessage;
        private set { if (Set(ref _errorMessage, value)) OnPropertyChanged(nameof(HasError)); }
    }
    public bool HasError => !string.IsNullOrWhiteSpace(ErrorMessage);
    public bool IsBusy
    {
        get => _isBusy;
        private set
        {
            if (!Set(ref _isBusy, value)) return;
            OnPropertyChanged(nameof(CanEditCode));
            JoinCommand.RaiseCanExecuteChanged();
        }
    }
    public bool CanEditCode => !IsBusy;
    public AsyncCommand JoinCommand { get; }
    public RelayCommand PasteCommand { get; }

    public static string NormalizeCode(string value) =>
        new(value.Where(char.IsLetterOrDigit).Take(8).Select(char.ToUpperInvariant).ToArray());

    private bool CanJoin() => !IsBusy && IsServiceReady && RoomCode.Length is >= 4 and <= 8;

    private async Task JoinAsync()
    {
        ErrorMessage = "";
        var submittedCode = RoomCode;
        try
        {
            IsBusy = true;
            var room = await Shell.Gateway.JoinTradeRoomAsync(submittedCode, _requestCancellation.Token);
            if (!ReferenceEquals(Shell.CurrentScreen, this) ||
                !string.Equals(submittedCode, RoomCode, StringComparison.Ordinal)) return;
            Shell.OpenTradeRoom(room, RoomMembershipRole.Member, SwitchRoomRole.Unassigned);
        }
        catch (OperationCanceledException) when (_requestCancellation.IsCancellationRequested) { }
        catch (UserFacingException error) { ErrorMessage = error.UserMessage; }
        finally { IsBusy = false; }
    }

    private void Paste()
    {
        var text = Shell.ReadClipboard();
        if (!string.IsNullOrWhiteSpace(text)) RoomCode = text;
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        JoinCommand.RaiseCanExecuteChanged();
    }

    public override Task OnNavigatedToAsync()
    {
        if (_requestCancellation.IsCancellationRequested)
        {
            _requestCancellation.Dispose();
            _requestCancellation = new CancellationTokenSource();
        }
        return Task.CompletedTask;
    }

    public override void OnNavigatedFrom() => _requestCancellation.Cancel();
}
