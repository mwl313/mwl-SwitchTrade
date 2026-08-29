using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "WPF navigation releases the polling token in OnNavigatedFrom.")]
public sealed class ProductionDiagnosticsScreenViewModel : ScreenViewModel
{
    private readonly CancellationTokenSource _lifetime = new();
    private ProductionDiagnosticViewData? _run;
    private HardwareDeviceViewData? _adapter;
    private string _statusMessage = "Choose a diagnostic to validate this PC before a separated two-PC test.";
    private string _supportFilePath = "";
    private bool _busy;
    private ProductionDiagnosticTest? _lastTest;

    public ProductionDiagnosticsScreenViewModel(MainViewModel shell) : base(shell)
    {
        StartCommand = new RelayCommand<ProductionDiagnosticTest>(test => _ = StartAsync(test),
            _ => IsServiceReady && !Busy && !IsActive && Adapter is not null);
        ContinueCommand = new RelayCommand(ContinueAsync, () => Run?.IsWaiting == true && !Busy);
        CancelCommand = new RelayCommand(CancelAsync, () => IsActive && !Busy);
        SupportCommand = new RelayCommand(CreateSupportAsync, () => Run?.IsTerminal == true && !Busy);
        RunAgainCommand = new RelayCommand(RunAgainAsync,
            () => _lastTest is not null && Run?.IsTerminal == true && !Busy && Adapter is not null);
    }

    public override string Title => "Production diagnostics";
    public IReadOnlyList<SelectionOption<ProductionDiagnosticTest>> Tests { get; } =
    [
        new(ProductionDiagnosticTest.Automated, "Run automated system check"),
        new(ProductionDiagnosticTest.RoomDetection, "Detect a Switch room"),
        new(ProductionDiagnosticTest.ApAssociation, "Test Switch AP association"),
        new(ProductionDiagnosticTest.Recommended, "Run recommended local suite"),
    ];
    public ObservableCollection<ProductionDiagnosticStageViewData> Stages { get; } = [];
    public ProductionDiagnosticViewData? Run
    {
        get => _run;
        private set
        {
            if (!Set(ref _run, value)) return;
            OnPropertyChanged(nameof(IsActive));
            OnPropertyChanged(nameof(HasRun));
            OnPropertyChanged(nameof(CurrentStage));
            OnPropertyChanged(nameof(CheckpointInstructions));
            OnPropertyChanged(nameof(HasCheckpoint));
            OnPropertyChanged(nameof(CheckpointDeadline));
            OnPropertyChanged(nameof(ResultSummary));
            StartCommand.RaiseCanExecuteChanged();
            ContinueCommand.RaiseCanExecuteChanged();
            CancelCommand.RaiseCanExecuteChanged();
            SupportCommand.RaiseCanExecuteChanged();
            RunAgainCommand.RaiseCanExecuteChanged();
        }
    }
    public HardwareDeviceViewData? Adapter
    {
        get => _adapter;
        private set
        {
            if (!Set(ref _adapter, value)) return;
            OnPropertyChanged(nameof(AdapterText));
            StartCommand.RaiseCanExecuteChanged();
            RunAgainCommand.RaiseCanExecuteChanged();
        }
    }
    public string AdapterText => Adapter is null
        ? "No selected adapter. Return to Connection settings and choose one."
        : $"Using {Adapter.DisplayLabel}";
    public string StatusMessage { get => _statusMessage; private set => Set(ref _statusMessage, value); }
    public string SupportFilePath { get => _supportFilePath; private set => Set(ref _supportFilePath, value); }
    public bool Busy
    {
        get => _busy;
        private set
        {
            if (!Set(ref _busy, value)) return;
            StartCommand.RaiseCanExecuteChanged();
            ContinueCommand.RaiseCanExecuteChanged();
            CancelCommand.RaiseCanExecuteChanged();
            SupportCommand.RaiseCanExecuteChanged();
            RunAgainCommand.RaiseCanExecuteChanged();
        }
    }
    public bool IsActive => Run is not null && !Run.IsTerminal;
    public bool HasRun => Run is not null;
    public bool HasCheckpoint => Run?.IsWaiting == true;
    public string CurrentStage => Run is null ? "Not running" : $"{Run.Status} · {Run.CurrentStage}";
    public string CheckpointInstructions => Run?.Checkpoint?.Instructions ?? "";
    public string CheckpointDeadline => Run?.Checkpoint?.Deadline is { } deadline
        ? $"Continue by {deadline.LocalDateTime:t}." : "";
    public string ResultSummary => Run is null ? "" : Run.IsTerminal
        ? Run.FailureCode is { Length: > 0 } code
            ? $"{code}: {Run.FailureMessage ?? "The diagnostic did not complete."}"
            : Run.Status == "passed" ? $"Passed: {Run.ResultLevel}." : Run.Status
        : "The diagnostic owns the selected adapter until cleanup finishes.";
    public RelayCommand<ProductionDiagnosticTest> StartCommand { get; }
    public RelayCommand ContinueCommand { get; }
    public RelayCommand CancelCommand { get; }
    public RelayCommand SupportCommand { get; }
    public RelayCommand RunAgainCommand { get; }

    public override async Task OnNavigatedToAsync()
    {
        if (!IsServiceReady) return;
        try
        {
            Adapter = (await Shell.Gateway.GetHardwareDevicesAsync(_lifetime.Token))
                .SingleOrDefault(device => device.IsSelected);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    public override void OnNavigatedFrom()
    {
        _lifetime.Cancel();
        _lifetime.Dispose();
    }

    private async Task StartAsync(ProductionDiagnosticTest test)
    {
        if (Adapter is null || Busy) return;
        Busy = true;
        try
        {
            SupportFilePath = "";
            StatusMessage = "Starting production diagnostics…";
            Apply(await Shell.Gateway.StartProductionDiagnosticAsync(test, Adapter.UsbId));
            _lastTest = test;
            RunAgainCommand.RaiseCanExecuteChanged();
            _ = PollAsync();
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
        finally { Busy = false; }
    }

    private async void ContinueAsync()
    {
        if (Run?.Checkpoint is null || Busy) return;
        Busy = true;
        try
        {
            Apply(await Shell.Gateway.ContinueProductionDiagnosticAsync(Run.RunId, Run.Checkpoint.Id));
            _ = PollAsync();
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
        finally { Busy = false; }
    }

    private async void CancelAsync()
    {
        await CancelAndCleanupAsync();
    }

    internal async Task<bool> CancelAndCleanupAsync()
    {
        if (!IsActive || Run is null) return true;
        Busy = true;
        try
        {
            Apply(await Shell.Gateway.CancelProductionDiagnosticAsync(Run.RunId));
            var deadline = DateTimeOffset.UtcNow.AddSeconds(35);
            while (Run is { IsTerminal: false } && DateTimeOffset.UtcNow < deadline)
            {
                await Task.Delay(350);
                Apply(await Shell.Gateway.GetProductionDiagnosticAsync(Run.RunId));
            }
            if (Run is { IsTerminal: false })
            {
                StatusMessage = "Cleanup is still in progress. Keep SwitchTrade open and try again.";
                return false;
            }
            return true;
        }
        catch (UserFacingException error)
        {
            StatusMessage = error.UserMessage;
            return false;
        }
        finally { Busy = false; }
    }

    private async void CreateSupportAsync()
    {
        Busy = true;
        try
        {
            SupportFilePath = await Shell.Gateway.CreateSupportBundleAsync();
            StatusMessage = "Support file saved to your Desktop.";
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
        finally { Busy = false; }
    }

    private async void RunAgainAsync()
    {
        if (_lastTest is { } test) await StartAsync(test);
    }

    private async Task PollAsync()
    {
        try
        {
            while (Run is { IsTerminal: false } && !_lifetime.IsCancellationRequested)
            {
                await Task.Delay(500, _lifetime.Token);
                if (Run is not null) Apply(await Shell.Gateway.GetProductionDiagnosticAsync(Run.RunId, _lifetime.Token));
            }
        }
        catch (OperationCanceledException) { }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private void Apply(ProductionDiagnosticViewData run)
    {
        Run = run;
        Stages.Clear();
        foreach (var stage in run.Stages) Stages.Add(stage);
        StatusMessage = run.IsTerminal ? ResultSummary : $"Running: {run.CurrentStage}";
    }
}
