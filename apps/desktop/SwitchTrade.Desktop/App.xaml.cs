using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Media3D;
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
    private ApplicationSession? _applicationSession;

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        EventManager.RegisterClassHandler(
            typeof(ComboBox),
            UIElement.PreviewMouseLeftButtonDownEvent,
            new MouseButtonEventHandler(ComboBoxPreviewMouseLeftButtonDown),
            true);
        SystemParameters.StaticPropertyChanged += SystemSettingChanged;
        UpdateHighContrastResources();
        if (e.Args.Contains("--session-self-test"))
        {
            Shutdown(ApplicationSession.SelfTest() ? 0 : 1);
            return;
        }
        if (e.Args.Contains("--self-test"))
        {
            var apiIsLocal = new Uri(ControlApiClient.ApiBase).IsLoopback;
            var codeNormalizes = JoinPrivateRoomScreenViewModel.NormalizeCode("ab-12 cd") == "AB12CD";
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
            var applicationSessionWorks = ApplicationSession.SelfTest();
            var capabilityGateWorks = new ControlStatus(
                "idle", "0.2.0", "self-test", false, false, false, null, null,
                Capabilities: ["public-directory.v1"]).HasCapability("public-directory.v1");
            var unexpectedReleaseGateRequests = 0;
            bool ReleaseGateAccepts(string runtimeRelease, string installedRelease)
            {
                using var client = new ControlApiClient(new SelfTestHttpHandler(request =>
                {
                    if (request.RequestUri?.AbsolutePath != "/api/v1/app/readiness")
                        unexpectedReleaseGateRequests++;
                    return Task.FromResult(JsonResponse(
                        "{\"contract_version\":\"local-app-readiness.v2\",\"product_version\":\"0.2.0\"," +
                        $"\"release_id\":\"{runtimeRelease}\",\"compatible\":true," +
                        "\"states\":{\"control\":{\"status\":\"ready\",\"user_message\":\"Ready\"," +
                        "\"technical_code\":\"control.ready\"}}}"));
                }), installedRelease);
                return client.TryGetStatusAsync().GetAwaiter().GetResult()?.Compatible == true;
            }
            var exactReleaseGateWorks = !ReleaseGateAccepts("release-a", "release-b") &&
                                        ReleaseGateAccepts("release-a", "release-a") &&
                                        unexpectedReleaseGateRequests == 0;
            var selectionBody = "";
            using var contractClient = new ControlApiClient(new SelfTestHttpHandler(async request =>
            {
                if (request.Method == HttpMethod.Get)
                    return JsonResponse("""
                        {"devices":[{"bus_id":"9-7","instance_id":"USB\\VID_0BDA&PID_818B\\RADIO-A",
                        "usb_id":"0bda:818b","description":"RTL8192EU","status":"beta-candidate",
                        "selectable":true,"experimental":false,"shared":false,
                        "attached":false,"selected":true}]}
                        """);
                selectionBody = await request.Content!.ReadAsStringAsync();
                return JsonResponse("{}");
            }));
            var hardware = contractClient.GetHardwareDevicesAsync().GetAwaiter().GetResult().Single();
            contractClient.SelectHardwareDeviceAsync(
                hardware.UsbId, hardware.InstanceId, hardware.BusId).GetAwaiter().GetResult();
            var hardwareContractWorks = hardware.InstanceId.EndsWith("RADIO-A", StringComparison.Ordinal) &&
                                        !hardware.IsShared &&
                                        selectionBody.Contains("instance_id", StringComparison.Ordinal);
            using var roomContractClient = new ControlApiClient(new SelfTestHttpHandler(_ =>
                Task.FromResult(JsonResponse("""
                    {"contract_version":"production-connection-run.v1","run_id":"run-1","revision":8,
                    "phase":"terminal","local_role":"b_ap_host","peer_state":"paired",
                    "functional":{"status":"failed","failure":{"component":"relay",
                    "stage":"relay","gate":"C2_BRIDGE","code":"relay.restart",
                    "message":"relay restarted"}},
                    "cleanup":{"status":"verified","verified":true,"failures":[]},
                    "room":{"room_id":"room-1","room_version":8,"name":"Resumed Room",
                    "visibility":"private","room_code":"ABC123","participants":2,
                    "membership_role":"member"},"allowed_actions":["retry","leave"]}
                    """))));
            var failedProjection = roomContractClient.TryGetTradeRoomAsync().GetAwaiter().GetResult();
            var attemptFailureContractWorks = failedProjection is
            {
                FailureCode: "relay.restart", FailureStage: "relay",
                FailureRecoverable: true, FailureAction: "export_support_logs", Room.RoomCode: "ABC123",
                LocalTrainerDisplayName: "Trainer", PartnerTrainerDisplayName: "",
            };
            UserFacingException? deadlineFailure = null;
            using (var deadlineClient = new ControlApiClient(new SelfTestHttpHandler(_ =>
                       Task.FromResult(JsonResponse("""
                           {"code":"reconnect_deadline_expired","message":"reconnect deadline expired",
                           "stage":"authentication","recoverable":false,"primary_action":"rejoin_room",
                           "correlation_id":"deadline-correlation"}
                           """, System.Net.HttpStatusCode.Gone)))))
            {
                try { deadlineClient.TryGetTradeRoomAsync().GetAwaiter().GetResult(); }
                catch (UserFacingException error) { deadlineFailure = error; }
            }
            var deadlineEnvelopeSurvives = deadlineFailure is
            {
                TechnicalCode: "reconnect_deadline_expired", Stage: "authentication",
                Recoverable: false, PrimaryAction: "rejoin_room", CorrelationId: "deadline-correlation",
            };
            UserFacingException? unmatchedFailure = null;
            using (var unmatchedClient = new ControlApiClient(new SelfTestHttpHandler(_ =>
                       Task.FromResult(JsonResponse("""
                           {"code":"reconnect_credential_invalid","message":"reconnect credential is invalid",
                           "stage":"authentication","recoverable":false,"primary_action":"rejoin_room",
                           "correlation_id":"unmatched-correlation"}
                           """, System.Net.HttpStatusCode.Unauthorized)))))
            {
                try { unmatchedClient.TryGetTradeRoomAsync().GetAwaiter().GetResult(); }
                catch (UserFacingException error) { unmatchedFailure = error; }
            }
            var unmatchedEnvelopeSurvives = unmatchedFailure is
            {
                TechnicalCode: "reconnect_credential_invalid", Stage: "authentication",
                Recoverable: false, PrimaryAction: "rejoin_room", CorrelationId: "unmatched-correlation",
            };
            var malformedInventoryContained = InventoryFailureCode(
                new SelfTestHttpHandler(_ => Task.FromResult(JsonResponse("{")))) ==
                "usb_inventory_invalid";
            var timedOutInventoryContained = InventoryFailureCode(
                new SelfTestHttpHandler(_ => Task.FromException<HttpResponseMessage>(
                    new TaskCanceledException("self-test timeout")))) == "usb_inventory_timeout";
            var fakeGateway = new SelfTestGateway();
            var coordinator = new ActiveTradeRoomCoordinator(fakeGateway);
            coordinator.Open(
                new TradeRoomInfo("Room", "ABC123", "private", 1, "self_test"),
                RoomMembershipRole.Owner, SwitchRoomRole.Creator);
            var coordinatorWorks = coordinator.StartConnectionAsync(
                                       SwitchRoomRole.Creator).GetAwaiter().GetResult() &&
                                   fakeGateway.LastSwitchRole == SwitchRoomRole.Creator &&
                                   coordinator.StopConnectionAsync().GetAwaiter().GetResult() &&
                                   fakeGateway.StopCount == 1 && fakeGateway.EndCount == 0 &&
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
            var activeGateway = new SelfTestGateway();
            var activeCoordinator = new ActiveTradeRoomCoordinator(activeGateway);
            activeCoordinator.Open(
                new TradeRoomInfo("Room", "ABC123", "private", 2, "self_test"),
                RoomMembershipRole.Owner, SwitchRoomRole.Creator);
            activeCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                6, 2, "running", RoomMembershipRole.Owner,
                SwitchRoomRole.Creator, true, true, "running", true,
                CurrentGate: "C_RFU_ACTIVE", LastPassedGate: "C_RFU_ACTIVE"));
            var activeEndWorks = activeCoordinator.ConnectionIsActive &&
                                 activeCoordinator.StopConnectionAsync().GetAwaiter().GetResult() &&
                                 activeGateway.EndCount == 1 && activeGateway.StopCount == 0;
            memberCoordinator.Open(
                new TradeRoomInfo("Room", "ABC123", "private", 2, "self_test"),
                RoomMembershipRole.Member, SwitchRoomRole.Unassigned);
            memberCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                4, 2, "connection_attempt", RoomMembershipRole.Member,
                SwitchRoomRole.Finder, true, true, "connecting_switches", true));
            var authoritativeProjectionWorks = memberCoordinator.RoleLocked &&
                                               memberCoordinator.BothReady &&
                                               memberCoordinator.AttemptPhase == "connecting_switches";
            memberCoordinator.ApplyRoom(failedProjection!);
            var attemptFailureMapsToRecovery =
                memberCoordinator.ConnectionState == LegacyConnectionState.NeedsRecovery &&
                memberCoordinator.RecoveryCode == "relay.restart" &&
                memberCoordinator.RecoveryStage == "relay" &&
                memberCoordinator.RecoveryRecoverable &&
                memberCoordinator.RecoveryAction == "export_support_logs" &&
                memberCoordinator.LocalTrainerDisplayName == "Trainer" &&
                memberCoordinator.PartnerTrainerDisplayName == "";
            memberCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                5, 2, "ready_check", RoomMembershipRole.Member,
                SwitchRoomRole.Finder, true, false, "failed", true,
                FailureCode: "radio.switch_room_not_found", FailureStage: "radio",
                FailureRecoverable: true, FailureAction: "recreate_switch_room"));
            var missingSwitchRoomMapsToRecovery =
                memberCoordinator.ConnectionState == LegacyConnectionState.NeedsRecovery &&
                memberCoordinator.RecoveryCode == "radio.switch_room_not_found" &&
                memberCoordinator.RecoveryAction == "recreate_switch_room" &&
                memberCoordinator.RecoveryMessage?.Contains(
                    "No Group Leader Switch room", StringComparison.Ordinal) == true;
            memberCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                6, 2, "ready_check", RoomMembershipRole.Member,
                SwitchRoomRole.Finder, true, false, "failed", true,
                FailureCode: "relay.peer_lost", FailureStage: "relay",
                FailureRecoverable: true, FailureAction: "retry"));
            var peerLossDoesNotMaskLocalFailure =
                memberCoordinator.RecoveryCode == "radio.switch_room_not_found";
            memberCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                7, 2, "ready_check", RoomMembershipRole.Member,
                SwitchRoomRole.Unassigned, true, false, "none", false));
            var endedAttemptStaysIdle =
                memberCoordinator.ConnectionState == LegacyConnectionState.Idle &&
                memberCoordinator.RecoveryCode is null;
            memberCoordinator.ApplyRoom(new AuthoritativeRoomProjection(
                8, 0, "closed", RoomMembershipRole.Member,
                SwitchRoomRole.Unassigned, false, false, "none", false));
            var remoteCloseClearsRoom = !memberCoordinator.HasRoom;
            var inventoryGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                AdapterProfiles = [new AdapterProfileViewData(
                    "0bda:818b", "RTL8192EU", "Beta candidate", "", "", true, false, "ldn")],
                HardwareDevices = [new HardwareDeviceViewData(
                    "9-7", "USB\\VID_0BDA&PID_818B\\RADIO-A", "0bda:818b", "RTL8192EU",
                    "Beta candidate", true, false, false, false, true)],
            };
            using var inventoryShell = new MainViewModel(
                inventoryGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService());
            inventoryShell.InitializeAsync().GetAwaiter().GetResult();
            var home = new HomeScreenViewModel(inventoryShell);
            home.LoadAdaptersAsync().GetAwaiter().GetResult();
            inventoryGateway.HardwareFailure = new UserFacingException(
                "Inventory failed.", "usb_inventory_timeout", "hardware", true,
                "run_hardware_diagnostics");
            home.LoadAdaptersAsync().GetAwaiter().GetResult();
            var lastGoodInventorySurvives = home.Devices.Count == 1 &&
                                            home.SelectedDevice?.InstanceId.EndsWith(
                                                "RADIO-A", StringComparison.Ordinal) == true &&
                                            home.AdapterStatus == "Inventory failed.";
            var noSelectionGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                HardwareDevices = [new HardwareDeviceViewData(
                    "9-7", "USB\\VID_0BDA&PID_818B\\RADIO-A", "0bda:818b", "RTL8192EU",
                    "Beta candidate", true, false, true, false, false)],
            };
            using var noSelectionShell = new MainViewModel(
                noSelectionGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService());
            noSelectionShell.InitializeAsync().GetAwaiter().GetResult();
            var noSelectionHome = new HomeScreenViewModel(noSelectionShell);
            noSelectionHome.LoadAdaptersAsync().GetAwaiter().GetResult();
            var missingAuthoritativeSelectionBlocksRuns =
                noSelectionHome.SelectedDevice is null &&
                noSelectionHome.AdapterStatus == "Select an adapter" &&
                !noSelectionHome.CreateCommand.CanExecute(null) &&
                !noSelectionHome.JoinCommand.CanExecute(null);
            var unsharedSelectionGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                HardwareDevices = [new HardwareDeviceViewData(
                    "9-7", "USB\\VID_0BDA&PID_818B\\RADIO-A", "0bda:818b", "RTL8192EU",
                    "Beta candidate", true, false, false, false, true)],
            };
            using var unsharedSelectionShell = new MainViewModel(
                unsharedSelectionGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService());
            unsharedSelectionShell.InitializeAsync().GetAwaiter().GetResult();
            var unsharedSelectionHome = new HomeScreenViewModel(unsharedSelectionShell);
            unsharedSelectionHome.LoadAdaptersAsync().GetAwaiter().GetResult();
            var unsharedAuthoritativeSelectionRequiresAuthorization =
                unsharedSelectionHome.NeedsAdapterAuthorization &&
                unsharedSelectionHome.AuthorizeAdapterCommand.CanExecute(null) &&
                !unsharedSelectionHome.CreateCommand.CanExecute(null);
            var selectionGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                HardwareDevices =
                [
                    new HardwareDeviceViewData(
                        "9-7", "USB\\VID_0BDA&PID_818B\\RADIO-A", "0bda:818b", "RTL8192EU A",
                        "Beta candidate", true, false, true, false, true),
                    new HardwareDeviceViewData(
                        "9-8", "USB\\VID_0BDA&PID_818B\\RADIO-B", "0bda:818b", "RTL8192EU B",
                        "Beta candidate", true, false, true, false, false),
                ],
            };
            using var selectionShell = new MainViewModel(
                selectionGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService());
            selectionShell.InitializeAsync().GetAwaiter().GetResult();
            var selectionHome = new HomeScreenViewModel(selectionShell);
            selectionHome.LoadAdaptersAsync().GetAwaiter().GetResult();
            selectionHome.SelectedDevice = selectionHome.Devices.Single(device =>
                device.InstanceId.EndsWith("RADIO-B", StringComparison.Ordinal));
            selectionHome.UseSelectedAdapterAsync().GetAwaiter().GetResult();
            var homeAdapterSelectionWorks = selectionGateway.SelectHardwareCount == 1 &&
                                            selectionHome.SelectedDevice?.InstanceId.EndsWith(
                                                "RADIO-B", StringComparison.Ordinal) == true &&
                                            selectionHome.AdapterStatus == "Ready";
            var authorizationGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                HardwareDevices = [new HardwareDeviceViewData(
                    "9-7", "USB\\VID_0BDA&PID_818B\\RADIO-A", "0bda:818b", "RTL8192EU",
                    "Beta candidate", true, false, false, false, true)],
            };
            var authorization = new SelfTestHardwareAuthorizationService();
            using var authorizationShell = new MainViewModel(
                authorizationGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService(), authorization);
            var adapterAuthorizationRecoveryWorks =
                authorizationShell.RepairAdapterAsync().GetAwaiter().GetResult() &&
                authorization.AuthorizationCount == 1 && authorizationGateway.RepairAdapterCount == 1;
            var resumedRoom = new TradeRoomInfo(
                "Resumed Room", "ABC123", "private", 1, "authoritative", "Leaf",
                GameVersionChoice.LeafGreen, GameLanguage.English);
            var resumeGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                ActiveRoom = new AuthoritativeRoomProjection(
                    9, 1, "waiting_for_partner", RoomMembershipRole.Owner,
                    SwitchRoomRole.Unassigned, false, false, "none", false, resumedRoom),
            };
            using var resumeShell = new MainViewModel(
                resumeGateway, new BackendLauncher(), new WindowsDialogService(),
                new WindowsClipboardService());
            resumeShell.InitializeAsync().GetAwaiter().GetResult();
            var startupResumeWorks = resumeGateway.RoomProbeCount == 1 &&
                                     resumeShell.CurrentScreen is TradeRoomScreenViewModel &&
                                     resumeShell.RoomCoordinator.Context?.Room.RoomCode == "ABC123";
            var deadlineGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                RoomFailure = new UserFacingException(
                    "The saved Trade Room reconnect window expired.",
                    "reconnect_deadline_expired", "authentication", false, "rejoin_room",
                    "deadline-correlation"),
            };
            using var deadlineShell = new MainViewModel(
                deadlineGateway, new BackendLauncher(),
                new SelfTestDialogService(DialogChoice.Cancel), new WindowsClipboardService());
            deadlineShell.InitializeAsync().GetAwaiter().GetResult();
            var deadlineRecoveryVisible = deadlineShell.CurrentScreen is RecoveryScreenViewModel &&
                                          deadlineShell.CanReturnHomeFromAuthorityRecovery &&
                                          !deadlineShell.CanAbandonLocalAuthority &&
                                          deadlineShell.RecoveryTechnicalDetails.Contains(
                                              "deadline-correlation", StringComparison.Ordinal);
            deadlineShell.ReturnHomeFromAuthorityRecovery();
            var deadlineReturnHomeWorks = deadlineShell.CurrentScreen is HomeScreenViewModel &&
                                          !deadlineShell.CanReturnHomeFromAuthorityRecovery;
            var unmatchedGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                RoomFailure = new UserFacingException(
                    "SwitchTrade can no longer verify the saved Trade Room access.",
                    "reconnect_credential_invalid", "authentication", false, "rejoin_room",
                    "unmatched-correlation"),
            };
            var confirmAbandon = new SelfTestDialogService(DialogChoice.Primary);
            using var unmatchedShell = new MainViewModel(
                unmatchedGateway, new BackendLauncher(), confirmAbandon,
                new WindowsClipboardService());
            unmatchedShell.InitializeAsync().GetAwaiter().GetResult();
            var unmatchedRecoveryVisible = unmatchedShell.CurrentScreen is RecoveryScreenViewModel &&
                                           unmatchedShell.CanAbandonLocalAuthority &&
                                           unmatchedShell.RecoveryStage == "authentication" &&
                                           unmatchedShell.RecoveryTechnicalDetails.Contains(
                                               "reconnect_credential_invalid", StringComparison.Ordinal);
            unmatchedShell.AbandonLocalAuthorityAsync().GetAwaiter().GetResult();
            var confirmedAbandonWorks = unmatchedGateway.AbandonCount == 1 &&
                                        confirmAbandon.LastRequest?.IsDestructive == true &&
                                        unmatchedShell.CurrentScreen is HomeScreenViewModel;
            var canceledGateway = new SelfTestGateway
            {
                Status = ReadyStatus(),
                RoomFailure = new UserFacingException(
                    "SwitchTrade can no longer verify the saved Trade Room access.",
                    "reconnect_credential_invalid", "authentication", false, "rejoin_room"),
            };
            var cancelAbandon = new SelfTestDialogService(DialogChoice.Cancel);
            using var canceledShell = new MainViewModel(
                canceledGateway, new BackendLauncher(), cancelAbandon,
                new WindowsClipboardService());
            canceledShell.InitializeAsync().GetAwaiter().GetResult();
            canceledShell.AbandonLocalAuthorityAsync().GetAwaiter().GetResult();
            var canceledAbandonPreservesAuthority = canceledGateway.AbandonCount == 0 &&
                                                    cancelAbandon.LastRequest?.IsDestructive == true &&
                                                    canceledShell.CurrentScreen is RecoveryScreenViewModel &&
                                                    canceledShell.CanAbandonLocalAuthority;
            var checks = new Dictionary<string, bool>
            {
                [nameof(apiIsLocal)] = apiIsLocal,
                [nameof(codeNormalizes)] = codeNormalizes,
                [nameof(requiredRoomFieldsWork)] = requiredRoomFieldsWork,
                [nameof(applicationSessionWorks)] = applicationSessionWorks,
                [nameof(highContrastResourcesLoad)] = highContrastResourcesLoad,
                [nameof(capabilityGateWorks)] = capabilityGateWorks,
                [nameof(exactReleaseGateWorks)] = exactReleaseGateWorks,
                [nameof(coordinatorWorks)] = coordinatorWorks,
                [nameof(memberReleaseWorks)] = memberReleaseWorks,
                [nameof(activeEndWorks)] = activeEndWorks,
                [nameof(authoritativeProjectionWorks)] = authoritativeProjectionWorks,
                [nameof(attemptFailureContractWorks)] = attemptFailureContractWorks,
                [nameof(attemptFailureMapsToRecovery)] = attemptFailureMapsToRecovery,
                [nameof(missingSwitchRoomMapsToRecovery)] = missingSwitchRoomMapsToRecovery,
                [nameof(peerLossDoesNotMaskLocalFailure)] = peerLossDoesNotMaskLocalFailure,
                [nameof(endedAttemptStaysIdle)] = endedAttemptStaysIdle,
                [nameof(remoteCloseClearsRoom)] = remoteCloseClearsRoom,
                [nameof(startupResumeWorks)] = startupResumeWorks,
                [nameof(deadlineEnvelopeSurvives)] = deadlineEnvelopeSurvives,
                [nameof(deadlineRecoveryVisible)] = deadlineRecoveryVisible,
                [nameof(deadlineReturnHomeWorks)] = deadlineReturnHomeWorks,
                [nameof(unmatchedEnvelopeSurvives)] = unmatchedEnvelopeSurvives,
                [nameof(unmatchedRecoveryVisible)] = unmatchedRecoveryVisible,
                [nameof(confirmedAbandonWorks)] = confirmedAbandonWorks,
                [nameof(canceledAbandonPreservesAuthority)] = canceledAbandonPreservesAuthority,
                [nameof(hardwareContractWorks)] = hardwareContractWorks,
                [nameof(malformedInventoryContained)] = malformedInventoryContained,
                [nameof(timedOutInventoryContained)] = timedOutInventoryContained,
                [nameof(lastGoodInventorySurvives)] = lastGoodInventorySurvives,
                [nameof(missingAuthoritativeSelectionBlocksRuns)] = missingAuthoritativeSelectionBlocksRuns,
                [nameof(unsharedAuthoritativeSelectionRequiresAuthorization)] =
                    unsharedAuthoritativeSelectionRequiresAuthorization,
                [nameof(homeAdapterSelectionWorks)] = homeAdapterSelectionWorks,
                [nameof(adapterAuthorizationRecoveryWorks)] = adapterAuthorizationRecoveryWorks,
            };
            var failedChecks = checks.Where(item => !item.Value).Select(item => item.Key).ToArray();
            File.WriteAllLines(Path.Combine(Path.GetTempPath(), "SwitchTrade-desktop-self-test.failures.txt"),
                failedChecks);
            Shutdown(failedChecks.Length == 0 ? 0 : 1);
            return;
        }
        _singleInstance = new Mutex(true, "Local\\SwitchTrade.Desktop", out var createdNew);
        if (!createdNew)
        {
            Shutdown(0);
            return;
        }
        try
        {
            _applicationSession = ApplicationSession.Create();
            new MainWindow(_applicationSession).Show();
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            MessageBox.Show(
                "SwitchTrade could not create its local support session. Run Setup Repair and try again.",
                "SwitchTrade needs attention", MessageBoxButton.OK, MessageBoxImage.Error);
            Shutdown(1);
        }
    }

    private static void ComboBoxPreviewMouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (sender is not ComboBox comboBox || !comboBox.IsEnabled || comboBox.IsEditable ||
            e.ChangedButton != MouseButton.Left || e.OriginalSource is not DependencyObject source ||
            !IsInsideComboBoxSurface(source, comboBox))
        {
            return;
        }

        comboBox.Focus();
        comboBox.IsDropDownOpen = !comboBox.IsDropDownOpen;
        e.Handled = true;
    }

    private static bool IsInsideComboBoxSurface(DependencyObject source, ComboBox comboBox)
    {
        for (DependencyObject? current = source; current is not null; current = GetParent(current))
        {
            if (ReferenceEquals(current, comboBox)) return true;
        }
        return false;
    }

    private static DependencyObject? GetParent(DependencyObject element) =>
        element is Visual or Visual3D
            ? VisualTreeHelper.GetParent(element)
            : LogicalTreeHelper.GetParent(element);

    private sealed class SelfTestGateway : IControlGateway
    {
        public ControlStatus? Status { get; init; }
        public IReadOnlyList<AdapterProfileViewData> AdapterProfiles { get; init; } = [];
        public IReadOnlyList<HardwareDeviceViewData> HardwareDevices { get; set; } = [];
        public UserFacingException? HardwareFailure { get; set; }
        public UserFacingException? RoomFailure { get; init; }
        public AuthoritativeRoomProjection? ActiveRoom { get; init; }
        public int RoomProbeCount { get; private set; }
        public int AbandonCount { get; private set; }
        public int RepairAdapterCount { get; private set; }
        public int SelectHardwareCount { get; private set; }
        public int StopCount { get; private set; }
        public int EndCount { get; private set; }
        public SwitchRoomRole? LastSwitchRole { get; private set; }
        public RoomMembershipRole? LastMembershipRole { get; private set; }
        public Task<ControlStatus?> TryGetStatusAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(Status);
        public Task<TradeRoomInfo> CreateTradeRoomAsync(TradeRoomCreateRequest request, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<TradeRoomInfo> JoinTradeRoomAsync(string roomCode, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<IReadOnlyList<PublicRoomListing>> GetPublicRoomsAsync(
            PublicRoomQuery query, CancellationToken cancellationToken = default) =>
            Task.FromResult<IReadOnlyList<PublicRoomListing>>([]);
        public Task<TradeRoomInfo> JoinPublicRoomAsync(
            string listingId, string trainerDisplayName, CancellationToken cancellationToken = default) =>
            throw new NotSupportedException();
        public Task<AuthoritativeRoomProjection?> TryGetTradeRoomAsync(CancellationToken cancellationToken = default)
        {
            RoomProbeCount++;
            return RoomFailure is null
                ? Task.FromResult(ActiveRoom)
                : Task.FromException<AuthoritativeRoomProjection?>(RoomFailure);
        }
        public Task StartConnectionAsync(SwitchRoomRole role, RoomMembershipRole membershipRole,
            string roomCode, CancellationToken cancellationToken = default)
        {
            LastSwitchRole = role;
            return Task.CompletedTask;
        }
        public Task ContinueConnectionAsync(
            string checkpointId, CancellationToken cancellationToken = default) => Task.CompletedTask;
        public Task StopConnectionAsync(CancellationToken cancellationToken = default)
        {
            StopCount++;
            return Task.CompletedTask;
        }
        public Task EndConnectionAsync(CancellationToken cancellationToken = default)
        {
            EndCount++;
            return Task.CompletedTask;
        }
        public Task ReleaseTradeRoomAsync(string roomCode, RoomMembershipRole role, CancellationToken cancellationToken = default)
        {
            LastMembershipRole = role;
            return Task.CompletedTask;
        }
        public Task AbandonLocalAuthorityAsync(CancellationToken cancellationToken = default)
        {
            AbandonCount++;
            return Task.CompletedTask;
        }
        public Task<IReadOnlyList<AdapterProfileViewData>> GetAdapterProfilesAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult(AdapterProfiles);
        public Task<IReadOnlyList<HardwareDeviceViewData>> GetHardwareDevicesAsync(CancellationToken cancellationToken = default) =>
            HardwareFailure is null
                ? Task.FromResult(HardwareDevices)
                : Task.FromException<IReadOnlyList<HardwareDeviceViewData>>(HardwareFailure);
        public Task SelectHardwareDeviceAsync(
            string usbId, string instanceId, string busId,
            CancellationToken cancellationToken = default)
        {
            SelectHardwareCount++;
            HardwareDevices = HardwareDevices.Select(device => device with
            {
                IsSelected = device.InstanceId == instanceId && device.BusId == busId &&
                             device.UsbId == usbId,
            }).ToArray();
            return Task.CompletedTask;
        }
        public Task<HardwareDiagnosticViewData> RunHardwareDiagnosticsAsync(
            string usbId, CancellationToken cancellationToken = default) =>
            Task.FromResult(new HardwareDiagnosticViewData("self-test", "partial", "Self-test", ""));
        public Task<LivePartyProjection?> TryGetPartiesAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult<LivePartyProjection?>(null);
        public Task RepairAdapterAsync(CancellationToken cancellationToken = default)
        {
            RepairAdapterCount++;
            return Task.CompletedTask;
        }
        public Task<string> CreateSupportBundleAsync(CancellationToken cancellationToken = default) =>
            Task.FromResult("");
        public void Dispose() { }

    }

    private sealed class SelfTestHttpHandler(
        Func<HttpRequestMessage, Task<HttpResponseMessage>> send) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken) => send(request);
    }

    private sealed class SelfTestDialogService(DialogChoice choice) : IDialogService
    {
        public DialogRequest? LastRequest { get; private set; }
        public DialogChoice Show(DialogRequest request)
        {
            LastRequest = request;
            return choice;
        }
    }

    private sealed class SelfTestHardwareAuthorizationService : IHardwareAuthorizationService
    {
        public int AuthorizationCount { get; private set; }
        public Task AuthorizeAsync(
            HardwareDeviceViewData device, CancellationToken cancellationToken = default)
        {
            AuthorizationCount++;
            return Task.CompletedTask;
        }
    }

    private static HttpResponseMessage JsonResponse(
        string json, System.Net.HttpStatusCode status = System.Net.HttpStatusCode.OK) => new(status)
    {
        Content = new StringContent(json, System.Text.Encoding.UTF8, "application/json"),
    };

    private static string InventoryFailureCode(HttpMessageHandler handler)
    {
        using var client = new ControlApiClient(handler);
        try
        {
            _ = client.GetHardwareDevicesAsync().GetAwaiter().GetResult();
            return "";
        }
        catch (UserFacingException error)
        {
            return error.PrimaryAction == "run_hardware_diagnostics" ? error.TechnicalCode ?? "" : "";
        }
    }

    private static ControlStatus ReadyStatus() => new(
        "idle", "0.2.0", "self-test", false, false, false, null, null,
        ControlApiClient.ReadinessContract, true,
        new Dictionary<string, ReadinessAxis>(StringComparer.OrdinalIgnoreCase)
        {
            ["control"] = new("ready", "Ready", "control.ready", null),
        });

    protected override void OnExit(ExitEventArgs e)
    {
        SystemParameters.StaticPropertyChanged -= SystemSettingChanged;
        try { _applicationSession?.Complete(); }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
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
