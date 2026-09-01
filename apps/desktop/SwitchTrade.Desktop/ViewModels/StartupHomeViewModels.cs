using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

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
        SupportCommand = new AsyncCommand(ExportSupportAsync);
    }

    public override string Title => "SwitchTrade needs attention";
    public string RecoverySummary => Shell.RecoverySummary;
    public string RecoveryInstructions => Shell.RecoveryInstructions;
    public string RecoveryTechnicalDetails => Shell.RecoveryTechnicalDetails;
    public bool ShowAbandonLocalAuthority => Shell.CanAbandonLocalAuthority;
    public bool ShowReturnHome => Shell.CanReturnHomeFromAuthorityRecovery;
    public AsyncCommand RetryCommand { get; }
    public AsyncCommand AbandonLocalAuthorityCommand { get; }
    public RelayCommand ReturnHomeCommand { get; }
    public AsyncCommand SupportCommand { get; }

    private async Task ExportSupportAsync()
    {
        try
        {
            var path = await Shell.ExportSupportLogsAsync();
            Shell.Announce($"Support file saved to your Desktop: {path}");
        }
        catch (Services.UserFacingException error) { Shell.Announce(error.UserMessage); }
    }

    public void NotifyRecoveryChanged()
    {
        OnPropertyChanged(nameof(RecoverySummary));
        OnPropertyChanged(nameof(RecoveryInstructions));
        OnPropertyChanged(nameof(RecoveryTechnicalDetails));
        OnPropertyChanged(nameof(ShowAbandonLocalAuthority));
        OnPropertyChanged(nameof(ShowReturnHome));
    }
}

public sealed class HomeScreenViewModel : ScreenViewModel
{
    private HardwareDeviceViewData? _selectedDevice;
    private string _adapterStatus = "Checking adapters...";
    private bool _loadingAdapters;

    public HomeScreenViewModel(MainViewModel shell) : base(shell)
    {
        CreateCommand = new RelayCommand(shell.OpenCreate, () => CanStartConnection);
        PublicCommand = new RelayCommand(
            shell.OpenPublicRooms, () => shell.IsPublicDirectoryAvailable);
        JoinCommand = new RelayCommand(shell.OpenPrivateJoin, () => CanStartConnection);
        AuthorizeAdapterCommand = new AsyncCommand(
            UseSelectedAdapterAsync, () => IsServiceReady && NeedsAdapterAuthorization);
    }

    public override string Title => "Home";
    public bool ShowAttention => !IsServiceReady;
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The message is a bindable property of this screen projection.")]
    public string AttentionText => "SwitchTrade needs attention before a connection can start.";
    public string PublicAvailabilityText => Shell.PublicDirectoryStatusText;
    public ObservableCollection<HardwareDeviceViewData> Devices { get; } = [];
    public HardwareDeviceViewData? SelectedDevice
    {
        get => _selectedDevice;
        set
        {
            if (!Set(ref _selectedDevice, value)) return;
            NotifyAdapterState();
        }
    }
    public bool CanStartConnection => IsServiceReady &&
        SelectedDevice is { IsSelected: true, IsShared: true, IsSelectable: true };
    public bool NeedsAdapterAuthorization =>
        SelectedDevice is { IsSelected: true, IsShared: false, IsSelectable: true };
    public string AdapterStatus { get => _adapterStatus; private set => Set(ref _adapterStatus, value); }
    public RelayCommand CreateCommand { get; }
    public RelayCommand PublicCommand { get; }
    public RelayCommand JoinCommand { get; }
    public AsyncCommand AuthorizeAdapterCommand { get; }

    public override Task OnNavigatedToAsync() => LoadAdaptersAsync();

    public async Task UseSelectedAdapterAsync()
    {
        if (_loadingAdapters || SelectedDevice is null) return;
        var device = SelectedDevice;
        if (!device.IsSelectable)
        {
            AdapterStatus = device.Disclaimer;
            Shell.Announce(AdapterStatus);
            return;
        }

        try
        {
            var changed = false;
            if (!device.IsSelected)
            {
                await Shell.Gateway.SelectHardwareDeviceAsync(
                    device.UsbId, device.InstanceId, device.BusId);
                changed = true;
            }
            if (!device.IsShared)
            {
                AdapterStatus = "Approve the Windows prompt.";
                Shell.Announce(AdapterStatus);
                await Shell.AuthorizeHardwareAsync(device);
                changed = true;
            }
            if (changed)
                await LoadAdaptersAsync();
            AdapterStatus = SelectedDevice is { IsSelected: true, IsShared: true, IsSelectable: true }
                ? "Ready"
                : SelectedDevice?.Disclaimer ?? "Adapter unavailable";
            Shell.Announce($"{device.FriendlyName} selected");
        }
        catch (UserFacingException error)
        {
            await LoadAdaptersAsync();
            AdapterStatus = error.UserMessage;
            Shell.Announce(AdapterStatus);
        }
    }

    internal async Task LoadAdaptersAsync()
    {
        if (!IsServiceReady)
        {
            AdapterStatus = "Local service unavailable";
            return;
        }

        _loadingAdapters = true;
        try
        {
            var devices = await Shell.Gateway.GetHardwareDevicesAsync();
            Devices.Clear();
            foreach (var device in devices) Devices.Add(device);
            SelectedDevice = Devices.FirstOrDefault(device => device.IsSelected);
            AdapterStatus = SelectedDevice is null
                ? Devices.Count == 0 ? "No compatible adapter found" : "Select an adapter"
                : SelectedDevice.IsShared && SelectedDevice.IsSelectable
                    ? "Ready"
                    : SelectedDevice.Disclaimer;
        }
        catch (UserFacingException error)
        {
            AdapterStatus = error.UserMessage;
            Shell.Announce(AdapterStatus);
        }
        finally
        {
            _loadingAdapters = false;
            NotifyAdapterState();
        }
    }

    private void NotifyAdapterState()
    {
        OnPropertyChanged(nameof(CanStartConnection));
        OnPropertyChanged(nameof(NeedsAdapterAuthorization));
        CreateCommand.RaiseCanExecuteChanged();
        JoinCommand.RaiseCanExecuteChanged();
        AuthorizeAdapterCommand.RaiseCanExecuteChanged();
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        CreateCommand.RaiseCanExecuteChanged();
        PublicCommand.RaiseCanExecuteChanged();
        JoinCommand.RaiseCanExecuteChanged();
        AuthorizeAdapterCommand.RaiseCanExecuteChanged();
        OnPropertyChanged(nameof(CanStartConnection));
        OnPropertyChanged(nameof(NeedsAdapterAuthorization));
        OnPropertyChanged(nameof(ShowAttention));
        OnPropertyChanged(nameof(AttentionText));
        OnPropertyChanged(nameof(PublicAvailabilityText));
    }
}
