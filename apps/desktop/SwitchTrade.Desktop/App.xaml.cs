using System.ComponentModel;
using System.Windows;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.Services;
using SwitchTrade.Desktop.State;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop;

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "WPF owns the Application lifetime; OnExit releases the single-instance mutex.")]
public partial class App : Application
{
    private ResourceDictionary? _highContrastResources;
    private Mutex? _singleInstance;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        SystemParameters.StaticPropertyChanged += SystemSettingChanged;
        UpdateHighContrastResources();
        if (e.Args.Contains("--self-test"))
        {
            var apiIsLocal = new Uri(ControlApiClient.ApiBase).IsLoopback;
            var codeNormalizes = JoinPrivateRoomScreenViewModel.NormalizeCode("ab-12 cd") == "AB12CD";
            var previewsAreExplicit = new PublicRoomPreviewProvider().GetRooms() is { Count: >= 3 } rooms &&
                                      rooms.All(room => room.PreviewId.StartsWith("demo-", StringComparison.Ordinal));
            var requiredRoomFieldsWork =
                !CreateTradeRoomScreenViewModel.RequiredFieldsComplete(
                    "Room", "Trainer", GameVersionChoice.None, GameLanguage.English) &&
                !CreateTradeRoomScreenViewModel.RequiredFieldsComplete(
                    "Room", "Trainer", GameVersionChoice.FireRed, GameLanguage.None) &&
                CreateTradeRoomScreenViewModel.RequiredFieldsComplete(
                    "Room", "Trainer", GameVersionChoice.FireRed, GameLanguage.English);
            var highContrast = new ResourceDictionary
            {
                Source = new Uri("Themes/HighContrast.xaml", UriKind.Relative),
            };
            var highContrastResourcesLoad = highContrast.Contains("PrimaryTextBrush") &&
                                            highContrast.Contains("FocusBrush");
            var fakeGateway = new SelfTestGateway();
            var coordinator = new ActiveTradeRoomCoordinator(fakeGateway);
            coordinator.Open(
                new TradeRoomInfo("Room", "ABC123", "private", 1, "self_test"),
                RoomMembershipRole.Owner, SwitchRoomRole.Creator);
            var coordinatorWorks = coordinator.StartConnectionAsync().GetAwaiter().GetResult() &&
                                   fakeGateway.LastSwitchRole == SwitchRoomRole.Creator &&
                                   coordinator.StopConnectionAsync().GetAwaiter().GetResult() &&
                                   coordinator.ReleaseRoomAsync().GetAwaiter().GetResult() &&
                                   fakeGateway.LastMembershipRole == RoomMembershipRole.Owner &&
                                   !coordinator.HasRoom;
            var memberGateway = new SelfTestGateway();
            var memberCoordinator = new ActiveTradeRoomCoordinator(memberGateway);
            memberCoordinator.Open(
                new TradeRoomInfo("Room", "ABC123", "private", 2, "self_test"),
                RoomMembershipRole.Member, SwitchRoomRole.Finder);
            var memberReleaseWorks = memberCoordinator.ReleaseRoomAsync().GetAwaiter().GetResult() &&
                                     memberGateway.LastMembershipRole == RoomMembershipRole.Member;
            Shutdown(apiIsLocal && codeNormalizes && previewsAreExplicit && requiredRoomFieldsWork &&
                     highContrastResourcesLoad &&
                     coordinatorWorks && memberReleaseWorks ? 0 : 1);
            return;
        }
        _singleInstance = new Mutex(true, "Local\\SwitchTrade.Desktop", out var createdNew);
        if (!createdNew)
        {
            Shutdown(0);
            return;
        }
        new MainWindow().Show();
    }

    private sealed class SelfTestGateway : IControlGateway
    {
        public SwitchRoomRole? LastSwitchRole { get; private set; }
        public RoomMembershipRole? LastMembershipRole { get; private set; }
        public Task<ControlStatus?> TryGetStatusAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<ControlStatus?>(null);
        public Task<TradeRoomInfo> CreateTradeRoomAsync(TradeRoomCreateRequest request, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<TradeRoomInfo> JoinTradeRoomAsync(string roomCode, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task StartConnectionAsync(SwitchRoomRole role, RoomMembershipRole membershipRole,
            string roomCode, CancellationToken cancellationToken = default)
        {
            LastSwitchRole = role;
            return Task.CompletedTask;
        }
        public Task StopConnectionAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task ReleaseTradeRoomAsync(string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default)
        {
            LastMembershipRole = role;
            return Task.CompletedTask;
        }
        public Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<AdapterProfileViewData>>([]);
        public Task<LivePartyProjection?> TryGetPartiesAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<LivePartyProjection?>(null);
        public Task RepairAdapterAsync(CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task<string> CreateSupportBundleAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult("");
        public void Dispose() { }
    }

    protected override void OnExit(ExitEventArgs e)
    {
        SystemParameters.StaticPropertyChanged -= SystemSettingChanged;
        if (_singleInstance is not null)
        {
            try { _singleInstance.ReleaseMutex(); }
            catch (ApplicationException) { }
            _singleInstance.Dispose();
        }
        base.OnExit(e);
    }

    private void SystemSettingChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SystemParameters.HighContrast)) UpdateHighContrastResources();
    }

    private void UpdateHighContrastResources()
    {
        if (SystemParameters.HighContrast)
        {
            if (_highContrastResources is not null) return;
            _highContrastResources = new ResourceDictionary
            {
                Source = new Uri("Themes/HighContrast.xaml", UriKind.Relative),
            };
            Resources.MergedDictionaries.Add(_highContrastResources);
        }
        else if (_highContrastResources is not null)
        {
            Resources.MergedDictionaries.Remove(_highContrastResources);
            _highContrastResources = null;
        }
    }
}
