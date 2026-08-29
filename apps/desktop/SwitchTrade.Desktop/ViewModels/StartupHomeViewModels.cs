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
        AbandonLocalAuthorityCommand = new AsyncCommand(shell.AbandonLocalAuthorityAsync);
        ReturnHomeCommand = new RelayCommand(shell.ReturnHomeFromAuthorityRecovery);
        SettingsCommand = new AsyncCommand(shell.OpenSettingsAsync);
    }

    public override string Title => "SwitchTrade needs attention";
    public string RecoverySummary => Shell.RecoverySummary;
    public string RecoveryInstructions => Shell.RecoveryInstructions;
    public string RecoveryTechnicalDetails => Shell.RecoveryTechnicalDetails;
    public bool ShowConnectionSettings => Shell.RecoveryStage == "radio";
    public bool ShowAbandonLocalAuthority => Shell.CanAbandonLocalAuthority;
    public bool ShowReturnHome => Shell.CanReturnHomeFromAuthorityRecovery;
    public AsyncCommand RetryCommand { get; }
    public AsyncCommand AbandonLocalAuthorityCommand { get; }
    public RelayCommand ReturnHomeCommand { get; }
    public AsyncCommand SettingsCommand { get; }

    public void NotifyRecoveryChanged()
    {
        OnPropertyChanged(nameof(RecoverySummary));
        OnPropertyChanged(nameof(RecoveryInstructions));
        OnPropertyChanged(nameof(RecoveryTechnicalDetails));
        OnPropertyChanged(nameof(ShowConnectionSettings));
        OnPropertyChanged(nameof(ShowAbandonLocalAuthority));
        OnPropertyChanged(nameof(ShowReturnHome));
    }
}

public sealed class HomeScreenViewModel : ScreenViewModel
{
    public HomeScreenViewModel(MainViewModel shell) : base(shell)
    {
        CreateCommand = new RelayCommand(shell.OpenCreate, () => shell.IsServiceReady);
        PublicCommand = new RelayCommand(
            shell.OpenPublicRooms, () => shell.IsPublicDirectoryAvailable);
        JoinCommand = new RelayCommand(shell.OpenPrivateJoin, () => shell.IsServiceReady);
    }

    public override string Title => "Home";
    public bool ShowAttention => !IsServiceReady;
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The message is a bindable property of this screen projection.")]
    public string AttentionText => "SwitchTrade needs attention before a connection can start.";
    public string PublicAvailabilityText => Shell.PublicDirectoryStatusText;
    public RelayCommand CreateCommand { get; }
    public RelayCommand PublicCommand { get; }
    public RelayCommand JoinCommand { get; }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        CreateCommand.RaiseCanExecuteChanged();
        PublicCommand.RaiseCanExecuteChanged();
        JoinCommand.RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(ShowAttention));
        OnPropertyChanged(nameof(AttentionText));
        OnPropertyChanged(nameof(PublicAvailabilityText));
    }
}
