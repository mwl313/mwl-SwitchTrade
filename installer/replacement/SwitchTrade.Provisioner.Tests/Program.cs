using System.Text;
using System.Text.Json;
using SwitchTrade.Provisioner;

var root = Path.Combine(Path.GetTempPath(), "switchtrade-provisioner-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    WslConfigPreservesUnrelatedSettings();
    ProductionKernelStorageIsAsciiAndUserScoped();
    ProcessOutputDecodesWindowsAndLinuxStreams();
    KernelApplyAndRestorePreserveUserChanges();
    KernelRestoreFailsClosedAfterOwnershipChange();
    ReleaseManifestVerifiesPayloadsAndRejectsEscape();
    RuntimeNamesAlwaysRetainUniqueGeneration();
    ProvisionerLogsAreSanitized();
    AtomicStateRoundTrip();
    await RuntimeStatusReconcilesIndependentRegistrationViews();
    await HardwareAuthorizationUsesStableIdentity();
    await LifecycleFaultsConverge();
    await ConcurrentOperationsAreRejected();
    await InterruptedOlderReleaseConvergesWithNewPackage();
    await LegacyMetadataIsRetiredOnlyAfterSuccessfulRepair();
    await OwnedLegacyRuntimeMigrates();
    await AmbiguousLegacyRuntimeFailsBeforeMutation();
    await PostCommitFaultConverges();
    await TransientNameOmissionCannotSkipCleanup();
    await FalseUnregisterSuccessRetainsRecovery();
    await OrphanedOwnedRuntimesAreReconciled();
    await AmbiguousOrphanFailsClosed();
    await ManagedRootsRemainIsolated();
    Console.WriteLine("SwitchTrade provisioner contract tests passed.");
    return 0;
}
finally
{
    Directory.Delete(root, true);
}

void WslConfigPreservesUnrelatedSettings()
{
    var input = "# user settings\r\n[wsl2]\r\nmemory=4GB\r\nkernel=C:\\\\old\\\\kernel\r\n[experimental]\r\nautoMemoryReclaim=gradual\r\n";
    var document = new TextDocument(input, new UTF8Encoding(false, true), false, "\r\n", true);
    var merged = WslConfig.Merge(document, new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
    {
        ["kernel"] = "C:\\\\new\\\\kernel",
        ["kernelModules"] = null,
    });
    Assert(merged.Contains("memory=4GB\r\n", StringComparison.Ordinal), "memory setting changed");
    Assert(merged.Contains("autoMemoryReclaim=gradual", StringComparison.Ordinal), "experimental setting changed");
    Assert(merged.Contains("kernel=C:\\\\new\\\\kernel", StringComparison.Ordinal), "kernel not replaced");
    Assert(!merged.Contains("old", StringComparison.Ordinal), "old kernel retained");
}

void ProductionKernelStorageIsAsciiAndUserScoped()
{
    var path = ProvisionerPaths.ProductionKernelRoot("C:\\ProgramData", "S-1-5-21-123-456-789-1001");
    Assert(path == "C:\\ProgramData\\SwitchTrade\\users\\S-1-5-21-123-456-789-1001\\kernel",
        "production kernel storage is not stable and user-scoped");
    Assert(path.All(character => character <= 0x7f),
        "production kernel storage unexpectedly depends on a Unicode profile path");
}

void ProcessOutputDecodesWindowsAndLinuxStreams()
{
    const string windowsText = "WSL 커스텀 커널을 찾을 수 없습니다.";
    const string linuxText = "{\"owner\":\"switchtrade-provisioner\"}";
    Assert(ProcessRunner.Decode(Encoding.Unicode.GetBytes(windowsText)) == windowsText,
        "UTF-16 WSL diagnostics were not decoded");
    Assert(ProcessRunner.Decode(Encoding.UTF8.GetBytes(linuxText)) == linuxText,
        "UTF-8 Linux output was not decoded");
}

async Task HardwareAuthorizationUsesStableIdentity()
{
    const string instanceId = "USB\\VID_0BDA&PID_818B\\RADIO-A";
    var shared = false;
    var commands = new List<string[]>();
    Task<ProcessResult> Run(IReadOnlyList<string> arguments, CancellationToken _)
    {
        commands.Add(arguments.ToArray());
        if (arguments.SequenceEqual(["bind", "--busid", "9-7"]))
        {
            shared = true;
            return Task.FromResult(new ProcessResult(0, "", ""));
        }
        if (arguments.SequenceEqual(["state"]))
            return Task.FromResult(new ProcessResult(0, $$"""
                {"Devices":[{"BusId":"9-7","InstanceId":"{{instanceId.Replace("\\", "\\\\", StringComparison.Ordinal)}}",
                "PersistedGuid":{{(shared ? "\"shared-guid\"" : "null")}},"StubInstanceId":null}]}
                """, ""));
        return Task.FromResult(new ProcessResult(1, "", "unexpected command"));
    }

    await HardwareAuthorization.AuthorizeAsync(
        instanceId, "0bda:818b", Run, () => true, CancellationToken.None);
    Assert(commands.Any(command => command.SequenceEqual(["bind", "--busid", "9-7"])),
        "hardware authorization did not bind the current bus for the stable identity");
    Assert(commands.Count(command => command.SequenceEqual(["state"])) == 2,
        "hardware authorization did not verify the final shared state");

    var changedIdentityRejected = false;
    try
    {
        await HardwareAuthorization.AuthorizeAsync(
            instanceId, "0e8d:7610", Run, () => true, CancellationToken.None);
    }
    catch (ProvisionerException error)
    {
        changedIdentityRejected = error.Code == "ADAPTER_IDENTITY_CHANGED";
    }
    Assert(changedIdentityRejected,
        "hardware authorization did not fail closed when the USB identity changed");
}

void KernelApplyAndRestorePreserveUserChanges()
{
    var data = Path.Combine(root, "kernel-roundtrip", "data");
    var profile = Path.Combine(root, "kernel-roundtrip", "사용자 profile");
    var package = Path.Combine(root, "kernel-roundtrip", "package");
    Directory.CreateDirectory(profile);
    Directory.CreateDirectory(Path.Combine(package, "payload"));
    var config = Path.Combine(profile, ".wslconfig");
    var original = "[wsl2]\r\nmemory=3GB\r\nkernel=C:\\\\user\\\\kernel\r\nkernelModules=C:\\\\user\\\\modules.vhdx\r\n";
    File.WriteAllText(config, original, new UnicodeEncoding(false, true));
    var kernel = Path.Combine(package, "payload", "kernel");
    File.WriteAllText(kernel, "kernel-one", Encoding.ASCII);
    var manifest = TestManifest(kernel, package);
    var paths = new ProvisionerPaths(data, profile);
    paths.Ensure();
    var manager = new KernelManager(paths);
    manager.Apply(manifest, package);
    var applied = TextDocument.Read(config);
    File.WriteAllText(config, WslConfig.Merge(applied,
        new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase) { ["processors"] = "2" }), applied.Encoding);
    manager.Restore();
    var restored = TextDocument.Read(config).Text;
    Assert(restored.Contains("kernel=C:\\\\user\\\\kernel", StringComparison.Ordinal), "prior kernel not restored");
    Assert(restored.Contains("kernelModules=C:\\\\user\\\\modules.vhdx", StringComparison.Ordinal), "prior modules not restored");
    Assert(restored.Contains("processors=2", StringComparison.Ordinal), "later unrelated setting not preserved");
}

void KernelRestoreFailsClosedAfterOwnershipChange()
{
    var data = Path.Combine(root, "kernel-conflict", "data");
    var profile = Path.Combine(root, "kernel-conflict", "profile");
    var package = Path.Combine(root, "kernel-conflict", "package");
    Directory.CreateDirectory(profile);
    Directory.CreateDirectory(Path.Combine(package, "payload"));
    var kernel = Path.Combine(package, "payload", "kernel");
    File.WriteAllText(kernel, "kernel-two", Encoding.ASCII);
    var paths = new ProvisionerPaths(data, profile);
    paths.Ensure();
    var manager = new KernelManager(paths);
    manager.Apply(TestManifest(kernel, package), package);
    File.WriteAllText(paths.WslConfigPath, "[wsl2]\r\nkernel=C:\\\\another\\\\kernel\r\n", new UTF8Encoding(false));
    try { manager.Restore(); throw new InvalidOperationException("ownership conflict was accepted"); }
    catch (ProvisionerException error) { Assert(error.Code == "WSLCONFIG_OWNERSHIP_CHANGED", "wrong ownership error"); }
    Assert(File.ReadAllText(paths.WslConfigPath).Contains("another", StringComparison.Ordinal), "conflicting config was overwritten");
}

void ReleaseManifestVerifiesPayloadsAndRejectsEscape()
{
    var package = Path.Combine(root, "manifest");
    Directory.CreateDirectory(Path.Combine(package, "payload"));
    var file = Path.Combine(package, "payload", "runtime.wsl");
    File.WriteAllText(file, "runtime", Encoding.ASCII);
    var manifest = new ReleaseManifest(1, "beta-test", "0.2.0-beta.1", "x64", 19045, "2.4.4",
        "local-app-readiness.v2", "https://relay.example.test", new string('1', 64),
        new KernelDescriptor("test", "rtl8xxxu", ["0bda:818b"], ["rtl8xxxu"]),
        new Dictionary<string, PayloadDescriptor> { ["runtime"] = new("payload/runtime.wsl", new FileInfo(file).Length, Contract.HashFile(file)) });
    File.WriteAllText(Path.Combine(package, "release-manifest.json"), JsonSerializer.Serialize(manifest, Contract.Json));
    Assert(ReleaseManifest.LoadVerified(package).ReleaseId == "beta-test", "valid manifest failed");
    Assert(ReleaseManifest.LoadVerified(package + Path.DirectorySeparatorChar).ReleaseId == "beta-test",
        "valid manifest with a trailing directory separator failed");
    var incompleteKernel = manifest with
    {
        Kernel = manifest.Kernel with { DriverModules = [] },
    };
    File.WriteAllText(Path.Combine(package, "release-manifest.json"),
        JsonSerializer.Serialize(incompleteKernel, Contract.Json));
    try { ReleaseManifest.LoadVerified(package); throw new InvalidOperationException("empty driver matrix accepted"); }
    catch (ProvisionerException error) { Assert(error.Code == "RELEASE_MANIFEST_INVALID", "wrong matrix error"); }
    var escaped = manifest with { Payloads = new Dictionary<string, PayloadDescriptor> { ["runtime"] = new("../outside", 1, new string('0', 64)) } };
    File.WriteAllText(Path.Combine(package, "release-manifest.json"), JsonSerializer.Serialize(escaped, Contract.Json));
    try { ReleaseManifest.LoadVerified(package); throw new InvalidOperationException("path escape accepted"); }
    catch (ProvisionerException error) { Assert(error.Code == "PAYLOAD_PATH_ESCAPE", "wrong path escape error"); }
}

void AtomicStateRoundTrip()
{
    var path = Path.Combine(root, "state", "active.json");
    var expected = new ActiveRuntime(1, "beta-test", "SwitchTrade-beta-test-a", null, "kernel", "local-app-readiness.v2");
    AtomicFile.Write(path, expected);
    Assert(AtomicFile.Read<ActiveRuntime>(path) == expected, "atomic state round trip failed");
    Assert(!Directory.EnumerateFiles(Path.GetDirectoryName(path)!, "*.tmp.*").Any(), "atomic temporary file leaked");
}

async Task RuntimeStatusReconcilesIndependentRegistrationViews()
{
    var test = Path.Combine(root, "runtime-status-reconciliation");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var paths = new ProvisionerPaths(data, profile);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var engine = new ProvisioningEngine(paths, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var active = AtomicFile.Read<ActiveRuntime>(paths.ActivePath)!;

    wsl.HideRegistrationFromNextLookup(active.ActiveName);
    var cliConfirmed = await engine.InspectAsync(CancellationToken.None);
    Assert(cliConfirmed.SoftwareReady,
        "a transient Lxss registry omission falsely marked a CLI-listed runtime corrupt");

    wsl.HideFromNextEnumeration(active.ActiveName);
    var registryConfirmed = await engine.InspectAsync(CancellationToken.None);
    Assert(registryConfirmed.SoftwareReady,
        "a transient CLI omission falsely marked a registry-confirmed runtime corrupt");

    wsl.HideFromNextEnumeration(active.ActiveName);
    wsl.HideRegistrationFromNextLookup(active.ActiveName);
    var reconciled = await engine.InspectAsync(CancellationToken.None);
    Assert(reconciled.SoftwareReady,
        "one transient omission from both views falsely marked the runtime corrupt");

    wsl.RemoveRegistrationForTest(active.ActiveName);
    var absent = await engine.InspectAsync(CancellationToken.None);
    Assert(!absent.SoftwareReady && absent.State == "corrupt",
        "runtime absence from both independent views did not fail closed");
}

void RuntimeNamesAlwaysRetainUniqueGeneration()
{
    var firstGeneration = Guid.Parse("11111111-1111-1111-1111-111111111111");
    var secondGeneration = Guid.Parse("22222222-2222-2222-2222-222222222222");
    var release = "beta-" + new string('x', 120);
    var first = ProvisioningEngine.RuntimeName(release, firstGeneration);
    var second = ProvisioningEngine.RuntimeName(release, secondGeneration);
    Assert(first.Length <= 63 && second.Length <= 63, "runtime name exceeds WSL limit");
    Assert(first.EndsWith(firstGeneration.ToString("N"), StringComparison.Ordinal),
        "runtime name lost its generation suffix");
    Assert(!first.Equals(second, StringComparison.Ordinal), "runtime generations collided");
}

void ProvisionerLogsAreSanitized()
{
    var paths = new ProvisionerPaths(Path.Combine(root, "log-sanitizing", "data"),
        Path.Combine(root, "log-sanitizing", "사용자 profile"));
    var correlation = Guid.Parse("44444444-4444-4444-4444-444444444444");
    ProvisionerLog.Write(paths, new ProvisionerEvent(1, "error", correlation, "repair",
        "test", Status: "failed", Code: "TEST", Message:
        $"path={paths.UserProfile}; token=do-not-log; data={paths.DataRoot}; kernel={paths.KernelRoot}"));
    var text = File.ReadAllText(Path.Combine(paths.LogRoot, correlation.ToString("N") + ".jsonl"));
    Assert(text.Contains("%USERPROFILE%", StringComparison.Ordinal) &&
           text.Contains("%SWITCHTRADE_DATA%", StringComparison.Ordinal) &&
           text.Contains("%SWITCHTRADE_KERNEL%", StringComparison.Ordinal),
        "provisioner log did not pseudonymize owned paths");
    Assert(!text.Contains("do-not-log", StringComparison.Ordinal),
        "provisioner log retained a token");
    var external = Path.Combine(root, "external-log", "burn.log");
    ProvisionerLog.Write(paths, new ProvisionerEvent(1, "error", correlation, "repair",
        "test", Status: "failed", Code: "TEST", Message: $"token=do-not-log; data={paths.DataRoot}"), external);
    var externalText = File.ReadAllText(external);
    Assert(externalText.Contains("%SWITCHTRADE_DATA%", StringComparison.Ordinal) &&
           !externalText.Contains("do-not-log", StringComparison.Ordinal),
        "external provisioner log was not sanitized");
}

async Task LifecycleFaultsConverge()
{
    foreach (var fault in new[] { "install", "marker", "kernel", "health" })
    {
        var test = Path.Combine(root, "fault-" + fault);
        var data = Path.Combine(test, "data");
        var profile = Path.Combine(test, "사용자 profile");
        var package = CreateLifecyclePackage(test);
        var manifest = ReleaseManifest.LoadVerified(package);
        var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, fault);
        var health = new FakeHealth(fault);
        var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl, health,
            Guid.NewGuid(), _ => { });
        try
        {
            await engine.RepairAsync(manifest, package, CancellationToken.None);
            throw new InvalidOperationException($"fault was not injected: {fault}");
        }
        catch (ProvisionerException) { }
        Assert(wsl.Names.Contains("Ubuntu"), "unrelated distro was touched");
        Assert(!wsl.Names.Any(name => name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal)),
            $"candidate survived {fault} fault");
        Assert(!File.Exists(Path.Combine(data, "state", "active-runtime.json")),
            $"active pointer committed after {fault} fault");
        Assert(!File.Exists(Path.Combine(profile, ".wslconfig")),
            $"kernel config was not rolled back after {fault} fault");

        await engine.RepairAsync(manifest, package, CancellationToken.None);
        var active = AtomicFile.Read<ActiveRuntime>(Path.Combine(data, "state", "active-runtime.json"));
        Assert(active is not null && wsl.Names.Contains(active.ActiveName),
            $"repair did not converge after {fault} fault");
        await engine.UninstallAsync(CancellationToken.None);
        Assert(wsl.Names.SetEquals(["Ubuntu"]), $"uninstall touched unrelated distro after {fault}");
        Assert(!File.Exists(Path.Combine(profile, ".wslconfig")),
            $"uninstall did not restore kernel config after {fault}");
    }
}

async Task ConcurrentOperationsAreRejected()
{
    var test = Path.Combine(root, "concurrent-operation");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var health = new BlockingHealth();
    var first = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl, health,
        Guid.NewGuid(), _ => { });
    var second = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    var running = first.RepairAsync(manifest, package, CancellationToken.None);
    await health.Entered.Task.WaitAsync(TimeSpan.FromSeconds(5));
    try
    {
        await second.RepairAsync(manifest, package, CancellationToken.None);
        throw new InvalidOperationException("concurrent provisioner operation was accepted");
    }
    catch (ProvisionerException error)
    {
        Assert(error.Code == "PROVISIONER_BUSY", "wrong concurrent-operation error");
    }
    health.Release.TrySetResult();
    await running;
    await first.UninstallAsync(CancellationToken.None);
}

async Task PostCommitFaultConverges()
{
    var test = Path.Combine(root, "fault-post-commit");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "unregister");
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var committed = AtomicFile.Read<ActiveRuntime>(Path.Combine(data, "state", "active-runtime.json"));
    Assert(committed is not null && wsl.Names.Contains(committed.ActiveName),
        "new active pointer was lost after post-commit fault");
    var pending = AtomicFile.Read<OperationJournal>(Path.Combine(data, "state", "operation.json"));
    Assert(pending is { Committed: true } && committed is { PreviousName: not null },
        "post-commit cleanup failure was not retained for a safe retry");
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var final = AtomicFile.Read<ActiveRuntime>(Path.Combine(data, "state", "active-runtime.json"));
    Assert(final is not null && wsl.Names.Count(name => name.StartsWith(
        "SwitchTrade-beta-", StringComparison.Ordinal)) == 1 && wsl.Names.Contains("Ubuntu"),
        "post-commit recovery did not converge to one owned runtime");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task TransientNameOmissionCannotSkipCleanup()
{
    var test = Path.Combine(root, "transient-name-omission");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var old = AtomicFile.Read<ActiveRuntime>(Path.Combine(data, "state", "active-runtime.json"))!;
    wsl.HideFromNextEnumeration(old.ActiveName);
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(wsl.UnregisterAttempts.Contains(old.ActiveName) && !wsl.Names.Contains(old.ActiveName),
        "a transient WSL name omission skipped verified previous-runtime cleanup");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task FalseUnregisterSuccessRetainsRecovery()
{
    var test = Path.Combine(root, "false-unregister-success");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "unregister-noop");
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var pending = AtomicFile.Read<OperationJournal>(Path.Combine(data, "state", "operation.json"));
    var active = AtomicFile.Read<ActiveRuntime>(Path.Combine(data, "state", "active-runtime.json"));
    Assert(pending is { Committed: true } && active is { PreviousName: not null } &&
        wsl.Names.Contains(active.PreviousName),
        "an incomplete unregister erased the cleanup recovery identity");
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(wsl.Names.Count(name => name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal)) == 1,
        "retry did not converge after an incomplete unregister");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task OrphanedOwnedRuntimesAreReconciled()
{
    var test = Path.Combine(root, "orphan-reconciliation");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var paths = new ProvisionerPaths(data, profile);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var engine = new ProvisioningEngine(paths, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var orphan = ProvisioningEngine.RuntimeName("beta-orphan", Guid.NewGuid());
    var orphanLocation = Path.Combine(paths.RuntimeRoot, orphan);
    wsl.SeedOwned(orphan, orphanLocation, "beta-orphan", new string('c', 64));
    var unregistered = ProvisioningEngine.RuntimeName("beta-unregistered", Guid.NewGuid());
    var unregisteredLocation = Path.Combine(paths.RuntimeRoot, unregistered);
    Directory.CreateDirectory(unregisteredLocation);
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(!wsl.Names.Contains(orphan) && !Directory.Exists(orphanLocation) &&
        !Directory.Exists(unregisteredLocation),
        "verified orphaned runtime storage was not reconciled");
    Assert(wsl.Names.Contains("Ubuntu"), "orphan reconciliation touched an unrelated distro");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task AmbiguousOrphanFailsClosed()
{
    var test = Path.Combine(root, "ambiguous-orphan");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var paths = new ProvisionerPaths(data, profile);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var engine = new ProvisioningEngine(paths, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var ambiguous = ProvisioningEngine.RuntimeName("beta-ambiguous", Guid.NewGuid());
    var location = Path.Combine(paths.RuntimeRoot, ambiguous);
    wsl.SeedUnowned(ambiguous, location);
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    var pending = AtomicFile.Read<OperationJournal>(paths.JournalPath);
    Assert(pending is { Committed: true } && wsl.Names.Contains(ambiguous) &&
        Directory.Exists(location),
        "ambiguous runtime ownership was deleted or its recovery guard was erased");
}

async Task ManagedRootsRemainIsolated()
{
    var test = Path.Combine(root, "managed-root-isolation");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var pathsA = new ProvisionerPaths(Path.Combine(test, "data-a"), Path.Combine(test, "profile-a"));
    var pathsB = new ProvisionerPaths(Path.Combine(test, "data-b"), Path.Combine(test, "profile-b"));
    var engineA = new ProvisioningEngine(pathsA, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    var engineB = new ProvisioningEngine(pathsB, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    await engineA.RepairAsync(manifest, package, CancellationToken.None);
    var runtimeA = AtomicFile.Read<ActiveRuntime>(pathsA.ActivePath)!.ActiveName;
    await engineB.RepairAsync(manifest, package, CancellationToken.None);
    var runtimeB = AtomicFile.Read<ActiveRuntime>(pathsB.ActivePath)!.ActiveName;
    Assert(wsl.Names.Contains(runtimeA) && wsl.Names.Contains(runtimeB),
        "one managed root treated another root's runtime as its orphan");
    await engineB.UninstallAsync(CancellationToken.None);
    Assert(wsl.Names.Contains(runtimeA) && !wsl.Names.Contains(runtimeB),
        "uninstall crossed the current managed runtime root");
    await engineA.UninstallAsync(CancellationToken.None);
}

async Task InterruptedOlderReleaseConvergesWithNewPackage()
{
    var test = Path.Combine(root, "cross-release-recovery");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var paths = new ProvisionerPaths(data, profile);
    paths.Ensure();
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var oldGeneration = Guid.Parse("33333333-3333-3333-3333-333333333333");
    var oldName = ProvisioningEngine.RuntimeName("beta-older-release", oldGeneration);
    var oldLocation = Path.Combine(paths.RuntimeRoot, oldName);
    var oldContent = new string('b', 64);
    wsl.SeedOwned(oldName, oldLocation, "beta-older-release", oldContent);
    AtomicFile.Write(paths.JournalPath, new OperationJournal(1, oldGeneration, "repair",
        "beta-older-release", oldContent, oldName, oldLocation, null, false));

    var engine = new ProvisioningEngine(paths, wsl, new FakeHealth("none"),
        Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(!wsl.Names.Contains(oldName), "new package did not clean an owned older candidate");
    Assert(wsl.Names.Count(name => name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal)) == 1,
        "cross-release recovery did not converge to one runtime");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task LegacyMetadataIsRetiredOnlyAfterSuccessfulRepair()
{
    var test = Path.Combine(root, "legacy-metadata");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    Directory.CreateDirectory(Path.Combine(data, "wsl"));
    Directory.CreateDirectory(Path.Combine(data, "recovery"));
    File.WriteAllText(Path.Combine(data, "recovery", "old-app.bin"), "owned recovery");
    File.WriteAllText(Path.Combine(data, "setup-resume.json"), "{}");
    File.WriteAllText(Path.Combine(data, "setup-transaction.json"), JsonSerializer.Serialize(new
    {
        schema = 3,
        distro_base_path = Path.Combine(data, "wsl"),
        distro_imported = false,
    }));
    var userConfiguration = Path.Combine(data, "user-config.json");
    File.WriteAllText(userConfiguration, "preserve during repair");
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });

    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(!File.Exists(Path.Combine(data, "setup-transaction.json")),
        "legacy transaction survived successful migration");
    Assert(!Directory.Exists(Path.Combine(data, "recovery")),
        "legacy recovery staging survived successful migration");
    Assert(File.Exists(userConfiguration), "repair removed persistent user configuration");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task OwnedLegacyRuntimeMigrates()
{
    var test = Path.Combine(root, "owned-legacy");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var installId = new string('5', 32);
    var legacyLocation = Path.Combine(data, "wsl");
    Directory.CreateDirectory(data);
    File.WriteAllText(Path.Combine(data, "setup-transaction.json"), JsonSerializer.Serialize(new
    {
        schema = 3, distro_base_path = legacyLocation, install_id = installId,
    }));
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    wsl.SeedLegacy(legacyLocation, installId);
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    await engine.RepairAsync(manifest, package, CancellationToken.None);
    Assert(!wsl.Names.Contains("SwitchTrade"), "owned legacy runtime survived migration");
    Assert(wsl.Names.Count(name => name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal)) == 1,
        "migration did not activate exactly one replacement runtime");
    await engine.UninstallAsync(CancellationToken.None);
}

async Task AmbiguousLegacyRuntimeFailsBeforeMutation()
{
    var test = Path.Combine(root, "ambiguous-legacy");
    var data = Path.Combine(test, "data");
    var profile = Path.Combine(test, "profile");
    var package = CreateLifecyclePackage(test);
    var manifest = ReleaseManifest.LoadVerified(package);
    var wsl = new FakeWsl(manifest.ReleaseId, manifest.RuntimeContentId, "none");
    wsl.SeedLegacy(Path.Combine(data, "wsl"), new string('6', 32));
    var engine = new ProvisioningEngine(new ProvisionerPaths(data, profile), wsl,
        new FakeHealth("none"), Guid.NewGuid(), _ => { });
    try
    {
        await engine.RepairAsync(manifest, package, CancellationToken.None);
        throw new InvalidOperationException("ambiguous legacy ownership was accepted");
    }
    catch (ProvisionerException error)
    {
        Assert(error.Code == "LEGACY_OWNERSHIP_AMBIGUOUS", "wrong ambiguous legacy error");
    }
    Assert(wsl.Names.SetEquals(["Ubuntu", "SwitchTrade"]),
        "ambiguous legacy failure mutated WSL registrations");
    Assert(!File.Exists(Path.Combine(data, "state", "active-runtime.json")),
        "ambiguous legacy failure committed replacement state");
}

string CreateLifecyclePackage(string test)
{
    var package = Path.Combine(test, "package");
    Directory.CreateDirectory(Path.Combine(package, "payload", "kernel"));
    var runtime = Path.Combine(package, "payload", "runtime.wsl");
    var kernel = Path.Combine(package, "payload", "kernel", "kernel");
    File.WriteAllText(runtime, "immutable-runtime", Encoding.ASCII);
    File.WriteAllText(kernel, "custom-kernel", Encoding.ASCII);
    var manifest = new ReleaseManifest(1, "beta-fault-test", "0.2.0", "x64", 19045, "2.4.4",
        "local-app-readiness.v2", "https://relay.example.test", new string('a', 64),
        new KernelDescriptor("test-kernel", "rtl8xxxu", ["0bda:818b"], ["rtl8xxxu"]),
        new Dictionary<string, PayloadDescriptor>
        {
            ["runtime"] = new("payload/runtime.wsl", new FileInfo(runtime).Length, Contract.HashFile(runtime)),
            ["kernel"] = new("payload/kernel/kernel", new FileInfo(kernel).Length, Contract.HashFile(kernel)),
        });
    File.WriteAllText(Path.Combine(package, "release-manifest.json"),
        JsonSerializer.Serialize(manifest, Contract.Json));
    return package;
}

ReleaseManifest TestManifest(string kernel, string package) => new(1, "beta-test", "0.2.0-beta.1", "x64", 19045, "2.4.4",
    "local-app-readiness.v2", "https://relay.example.test", new string('1', 64),
    new KernelDescriptor("test-kernel", "rtl8xxxu", ["0bda:818b"], ["rtl8xxxu"]),
    new Dictionary<string, PayloadDescriptor> { ["kernel"] = new(Path.GetRelativePath(package, kernel), new FileInfo(kernel).Length, Contract.HashFile(kernel)) });

static void Assert(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

sealed class FakeHealth(string fault) : IRuntimeHealth
{
    private bool _failed;
    public Task CheckAsync(string name, string releaseId, string contract, CancellationToken cancellationToken)
    {
        if (fault == "health" && !_failed)
        {
            _failed = true;
            throw ProvisionerException.Wsl("INJECTED_HEALTH_FAILURE", "injected health failure");
        }
        return Task.CompletedTask;
    }
}

sealed class BlockingHealth : IRuntimeHealth
{
    internal TaskCompletionSource Entered { get; } = new(
        TaskCreationOptions.RunContinuationsAsynchronously);
    internal TaskCompletionSource Release { get; } = new(
        TaskCreationOptions.RunContinuationsAsynchronously);

    public async Task CheckAsync(string name, string releaseId, string contract,
        CancellationToken cancellationToken)
    {
        Entered.TrySetResult();
        await Release.Task.WaitAsync(cancellationToken);
    }
}

sealed class FakeWsl(string releaseId, string contentId, string fault) : IWslPlatform
{
    private readonly Dictionary<string, WslRegistration> _registrations = new(StringComparer.OrdinalIgnoreCase)
    {
        ["Ubuntu"] = new WslRegistration("Ubuntu", Path.Combine(Path.GetTempPath(), "unrelated-ubuntu")),
    };
    private readonly Dictionary<string, RuntimeOwnership> _markers = new(StringComparer.OrdinalIgnoreCase);
    private readonly Dictionary<string, string> _rawMarkers = new(StringComparer.OrdinalIgnoreCase);
    private bool _failed;
    private string? _hiddenFromNextEnumeration;
    private string? _hiddenFromNextRegistration;

    public HashSet<string> Names => _registrations.Keys.ToHashSet(StringComparer.OrdinalIgnoreCase);
    public HashSet<string> UnregisterAttempts { get; } = new(StringComparer.OrdinalIgnoreCase);
    public Task<Version> VersionAsync(CancellationToken cancellationToken) => Task.FromResult(new Version(2, 7, 12));
    public Task<HashSet<string>> NamesAsync(CancellationToken cancellationToken)
    {
        var names = Names;
        if (_hiddenFromNextEnumeration is not null)
        {
            names.Remove(_hiddenFromNextEnumeration);
            _hiddenFromNextEnumeration = null;
        }
        return Task.FromResult(names);
    }
    public WslRegistration? Registration(string name)
    {
        if (string.Equals(_hiddenFromNextRegistration, name, StringComparison.OrdinalIgnoreCase))
        {
            _hiddenFromNextRegistration = null;
            return null;
        }
        return _registrations.GetValueOrDefault(name);
    }
    public void HideFromNextEnumeration(string name) => _hiddenFromNextEnumeration = name;
    public void HideRegistrationFromNextLookup(string name) => _hiddenFromNextRegistration = name;
    public void RemoveRegistrationForTest(string name) => _registrations.Remove(name);

    public void SeedOwned(string name, string location, string markerRelease, string markerContent)
    {
        Directory.CreateDirectory(location);
        _registrations[name] = new WslRegistration(name, location);
        _markers[name] = new RuntimeOwnership(
            1, "switchtrade-provisioner", "SwitchTrade", markerRelease, markerContent);
    }

    public void SeedLegacy(string location, string installId)
    {
        Directory.CreateDirectory(location);
        _registrations["SwitchTrade"] = new WslRegistration("SwitchTrade", location);
        _rawMarkers["SwitchTrade"] = JsonSerializer.Serialize(new
        {
            schema = 2, owner = "switchtrade-installer", product = "SwitchTrade",
            install_id = installId, release_id = "legacy",
        });
    }

    public void SeedUnowned(string name, string location)
    {
        Directory.CreateDirectory(location);
        _registrations[name] = new WslRegistration(name, location);
        _rawMarkers[name] = "{\"schema\":1,\"owner\":\"somebody-else\"}";
    }

    public Task InstallAsync(string appliance, string name, string location, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(location);
        _registrations[name] = new WslRegistration(name, location);
        _markers[name] = new RuntimeOwnership(
            1, "switchtrade-provisioner", "SwitchTrade", releaseId, contentId);
        if (fault == "install" && !_failed)
        {
            _failed = true;
            throw ProvisionerException.Wsl("INJECTED_INSTALL_FAILURE", "injected install failure");
        }
        return Task.CompletedTask;
    }

    public Task<ProcessResult> RunAsync(string name, IEnumerable<string> arguments, TimeSpan timeout,
        CancellationToken cancellationToken)
    {
        if (arguments.SequenceEqual(["uname", "-r"]))
        {
            if (fault == "kernel" && !_failed)
            {
                _failed = true;
                return Task.FromResult(new ProcessResult(0, "stock-kernel", ""));
            }
            return Task.FromResult(new ProcessResult(0, "test-kernel", ""));
        }
        if (fault == "marker" && !_failed)
        {
            _failed = true;
            throw ProvisionerException.Wsl("INJECTED_MARKER_FAILURE", "injected marker failure");
        }
        if (_rawMarkers.TryGetValue(name, out var rawMarker))
            return Task.FromResult(new ProcessResult(0, rawMarker, ""));
        if (!_markers.TryGetValue(name, out var ownership))
            return Task.FromResult(new ProcessResult(1, "", "marker missing"));
        var marker = JsonSerializer.Serialize(ownership, Contract.Json);
        return Task.FromResult(new ProcessResult(0, marker, ""));
    }

    public Task TerminateAsync(string name, CancellationToken cancellationToken) => Task.CompletedTask;
    public Task UnregisterAsync(string name, CancellationToken cancellationToken)
    {
        UnregisterAttempts.Add(name);
        if (fault == "unregister" && !_failed &&
            name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal))
        {
            _failed = true;
            throw ProvisionerException.Wsl("INJECTED_UNREGISTER_FAILURE", "injected unregister failure");
        }
        if (fault == "unregister-noop" && !_failed &&
            name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal))
        {
            _failed = true;
            return Task.CompletedTask;
        }
        _markers.Remove(name);
        _rawMarkers.Remove(name);
        if (_registrations.Remove(name, out var registration) && Directory.Exists(registration.BasePath))
            Directory.Delete(registration.BasePath, true);
        return Task.CompletedTask;
    }
    public Task ShutdownAsync(CancellationToken cancellationToken) => Task.CompletedTask;
}
