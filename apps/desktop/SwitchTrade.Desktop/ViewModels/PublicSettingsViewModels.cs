
using System.Collections.ObjectModel;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;

namespace SwitchTrade.Desktop.ViewModels;

public enum SettingsSection { Connection, Support, Advanced }

public sealed class SettingsScreenViewModel : ScreenViewModel
{
    private string _statusMessage = "";
    private string _supportFilePath = "";
    private string _diagnosticFilePath = "";
    private AdapterProfileViewData? _selectedAdapter;
    private HardwareDeviceViewData? _selectedDevice;
    private SettingsSection _selectedSection;

    public SettingsScreenViewModel(MainViewModel shell) : base(shell)
    {
        RecheckCommand = new AsyncCommand(LoadAsync);
        SupportCommand = new AsyncCommand(CreateSupportAsync, () => IsServiceReady);
        DiagnosticCommand = new AsyncCommand(
            RunDiagnosticsAsync, () => IsServiceReady && SelectedAdapter is not null);
        SelectDeviceCommand = new AsyncCommand(
            SelectDeviceAsync, () => IsServiceReady && SelectedDevice?.IsSelectable == true);
        CopySupportPathCommand = new RelayCommand(
            () => Shell.Copy(SupportFilePath, "Support file location copied"), () => HasSupportFile);
    }

    public override string Title => "Settings";
    public IReadOnlyList<SelectionOption<SettingsSection>> Sections { get; } =
    [
        new(SettingsSection.Connection, "Connection"),
        new(SettingsSection.Support, "Support"),
        new(SettingsSection.Advanced, "Advanced"),
    ];
    public SettingsSection SelectedSection { get => _selectedSection; set => Set(ref _selectedSection, value); }
    public ObservableCollection<AdapterProfileViewData> Adapters { get; } = [];
    public ObservableCollection<HardwareDeviceViewData> Devices { get; } = [];
    public HardwareDeviceViewData? SelectedDevice
    {
        get => _selectedDevice;
        set
        {
            if (!Set(ref _selectedDevice, value)) return;
            if (value is not null)
                SelectedAdapter = Adapters.FirstOrDefault(profile => profile.UsbId == value.UsbId);
            SelectDeviceCommand.RaiseCanExecuteChanged();
            OnPropertyChanged(nameof(DeviceDisclaimer));
        }
    }
    public string DeviceDisclaimer => SelectedDevice?.Disclaimer ??
        "Connect a profiled USB Wi-Fi adapter, then check again.";
    public AdapterProfileViewData? SelectedAdapter
    {
        get => _selectedAdapter;
        set
        {
            if (!Set(ref _selectedAdapter, value)) return;
            DiagnosticCommand.RaiseCanExecuteChanged();
        }
    }
    public string StatusMessage { get => _statusMessage; private set => Set(ref _statusMessage, value); }
    public string SupportFilePath
    {
        get => _supportFilePath;
        private set
        {
            if (!Set(ref _supportFilePath, value)) return;
            OnPropertyChanged(nameof(HasSupportFile));
            CopySupportPathCommand.RaiseCanExecuteChanged();
        }
    }
    public bool HasSupportFile => !string.IsNullOrWhiteSpace(SupportFilePath);
    public string DiagnosticFilePath
    {
        get => _diagnosticFilePath;
        private set => Set(ref _diagnosticFilePath, value);
    }
    public AsyncCommand RecheckCommand { get; }
    public AsyncCommand SupportCommand { get; }
    public AsyncCommand DiagnosticCommand { get; }
    public AsyncCommand SelectDeviceCommand { get; }
    public RelayCommand CopySupportPathCommand { get; }

    public override Task OnNavigatedToAsync() => LoadAsync();

    public async Task LoadAsync()
    {
        SelectedDevice = null;
        SelectedAdapter = null;
        Adapters.Clear();
        Devices.Clear();
        if (!IsServiceReady)
        {
            StatusMessage = "Connect the installed SwitchTrade runtime to check Wi-Fi adapters.";
            return;
        }
        try
        {
            foreach (var adapter in await Shell.Gateway.GetAdapterProfilesAsync()) Adapters.Add(adapter);
            foreach (var device in await Shell.Gateway.GetHardwareDevicesAsync()) Devices.Add(device);
            SelectedDevice = Devices.FirstOrDefault(device => device.IsSelected) ?? Devices.FirstOrDefault();
            SelectedAdapter ??= Adapters.FirstOrDefault();
            StatusMessage = Devices.Count == 0
                ? "No profiled USB Wi-Fi adapter is currently visible to Windows."
                : "Choose the adapter SwitchTrade should use. Experimental adapters are untested and may not work.";
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private async Task SelectDeviceAsync()
    {
        if (SelectedDevice is null) return;
        try
        {
            await Shell.Gateway.SelectHardwareDeviceAsync(SelectedDevice.UsbId, SelectedDevice.BusId);
            StatusMessage = $"{SelectedDevice.FriendlyName} will be used for the next connection.";
            Shell.Announce(StatusMessage);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private async Task RunDiagnosticsAsync()
    {
        if (SelectedAdapter is null) return;
        try
        {
            StatusMessage = $"Checking {SelectedAdapter.FriendlyName}...";
            var result = await Shell.Gateway.RunHardwareDiagnosticsAsync(SelectedAdapter.UsbId);
            DiagnosticFilePath = result.ReportPath;
            StatusMessage = $"Diagnostics {result.OverallStatus}: {result.Summary}";
            Shell.Announce(StatusMessage);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    private async Task CreateSupportAsync()
    {
        try
        {
            SupportFilePath = await Shell.Gateway.CreateSupportBundleAsync();
            StatusMessage = "Support file created.";
            Shell.Announce(StatusMessage);
        }
        catch (UserFacingException error) { StatusMessage = error.UserMessage; }
    }

    public override void NotifyShellState()
    {
        base.NotifyShellState();
        SupportCommand.RaiseCanExecuteChanged();
        DiagnosticCommand.RaiseCanExecuteChanged();
        SelectDeviceCommand.RaiseCanExecuteChanged();
    }
}
