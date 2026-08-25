namespace SwitchTrade.Desktop.ViewModels;

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
    public string RecoverySummary => Shell.RecoverySummary;
    public string RecoveryTechnicalDetails => Shell.RecoveryTechnicalDetails;
    public AsyncCommand RetryCommand { get; }
    public RelayCommand PreviewCommand { get; }
    public RelayCommand SettingsCommand { get; }
}

public sealed class HomeScreenViewModel : ScreenViewModel
{
    public HomeScreenViewModel(MainViewModel shell, bool interfacePreview = false) : base(shell)
    {
        IsInterfacePreview = interfacePreview;
        CreateCommand = new RelayCommand(shell.OpenCreate, () => shell.IsServiceReady);
        PublicCommand = new RelayCommand(shell.OpenPublicRooms);
        JoinCommand = new RelayCommand(shell.OpenPrivateJoin, () => shell.IsServiceReady);
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
        CreateCommand.RaiseCanExecuteChanged();
        JoinCommand.RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(ShowAttention));
        OnPropertyChanged(nameof(AttentionText));
    }
}
