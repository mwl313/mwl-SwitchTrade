using System.Text.Json;
using System.Text.RegularExpressions;

namespace SwitchTrade.Provisioner;

internal sealed partial class ProvisioningEngine(
    ProvisionerPaths paths, IWslPlatform wsl, IRuntimeHealth health,
    Guid correlationId, Action<ProvisionerEvent> emit)
{
    [GeneratedRegex("[^A-Za-z0-9._-]", RegexOptions.CultureInvariant)]
    private static partial Regex UnsafeName();

    internal async Task<ProvisionerStatus> InspectAsync(CancellationToken cancellationToken)
    {
        paths.Ensure();
        var journal = AtomicFile.Read<OperationJournal>(paths.JournalPath);
        var active = AtomicFile.Read<ActiveRuntime>(paths.ActivePath);
        HashSet<string> names;
        try { names = await wsl.NamesAsync(cancellationToken); }
        catch (ProvisionerException error) when (error.Code is "WSL_PREREQUISITE_MISSING" or "WSL_ENUMERATION_FAILED")
        {
            return new ProvisionerStatus(1, "wsl_missing", false, null, null, null, null, "Run SwitchTrade Setup");
        }

        if (journal is { Committed: false } && active?.ActiveName != journal.CandidateName)
            return new ProvisionerStatus(1, "partial", false, journal.ReleaseId, active?.ActiveName,
                active?.KernelRelease, active?.ControlContract, "Run Setup Repair");
        if (active is null)
        {
            var legacyFiles = File.Exists(Path.Combine(paths.DataRoot, "setup-transaction.json")) ||
                              File.Exists(Path.Combine(paths.DataRoot, "setup-resume.json"));
            var state = names.Contains("SwitchTrade") || legacyFiles ? "legacy" : "absent";
            return new ProvisionerStatus(1, state, false, null, null, null, null,
                state == "legacy" ? "Run Setup Repair" : null);
        }
        if (wsl.Registration(active.ActiveName) is null)
            return new ProvisionerStatus(1, "corrupt", false, active.ReleaseId, active.ActiveName,
                active.KernelRelease, active.ControlContract, "Run Setup Repair");
        var kernel = AtomicFile.Read<KernelState>(paths.KernelStatePath);
        var ready = kernel is not null && File.Exists(kernel.InstalledKernel) &&
            Contract.HashFile(kernel.InstalledKernel) == kernel.InstalledKernelSha256;
        var readyState = journal is not null ? "software_ready_cleanup_pending" : "software_ready";
        return new ProvisionerStatus(1, ready ? readyState : "kernel_invalid", ready,
            active.ReleaseId, active.ActiveName, active.KernelRelease, active.ControlContract,
            ready ? null : "Run Setup Repair");
    }

    internal async Task InstallAsync(ReleaseManifest manifest, string packageRoot, CancellationToken cancellationToken)
    {
        var status = await InspectAsync(cancellationToken);
        if (status.State != "absent")
            throw ProvisionerException.State("INSTALL_REQUIRES_ABSENT_STATE",
                "Install is fresh-only. Existing or partial SwitchTrade state must use Repair.");
        await ReplaceAsync("install", manifest, packageRoot, null, cancellationToken);
    }

    internal async Task RepairAsync(ReleaseManifest manifest, string packageRoot, CancellationToken cancellationToken)
    {
        await RecoverInterruptedAsync(manifest, cancellationToken);
        var active = AtomicFile.Read<ActiveRuntime>(paths.ActivePath);
        if (active is null && await LegacyExistsAsync(cancellationToken))
            await VerifyLegacyOwnedAsync(cancellationToken);
        await ReplaceAsync("repair", manifest, packageRoot, active, cancellationToken);
    }

    internal async Task UninstallAsync(CancellationToken cancellationToken)
    {
        using var operationLock = AcquireLock();
        Progress("uninstall", "state_inspection", 5, "Inspecting owned SwitchTrade resources");
        var active = AtomicFile.Read<ActiveRuntime>(paths.ActivePath);
        var journal = AtomicFile.Read<OperationJournal>(paths.JournalPath);
        var targets = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (active is not null)
        {
            targets.Add(active.ActiveName);
            if (active.PreviousName is not null) targets.Add(active.PreviousName);
        }
        if (journal?.CandidateName is not null) targets.Add(journal.CandidateName);

        foreach (var name in targets)
            await RemoveOwnedRuntimeAsync(name, null, null, null, cancellationToken);
        await RemoveOrphanedOwnedRuntimesAsync("", cancellationToken);
        if (await LegacyExistsAsync(cancellationToken)) await RemoveLegacyAsync(cancellationToken);

        Progress("uninstall", "kernel_configuration", 65, "Restoring the previous WSL kernel configuration");
        new KernelManager(paths).Restore();
        await wsl.ShutdownAsync(cancellationToken);
        RemoveOwnedTree(paths.RuntimeRoot, paths.DataRoot);
        RemoveOwnedTree(paths.KernelRoot, Path.GetDirectoryName(paths.KernelRoot));
        RemoveOwnedTree(Path.Combine(paths.DataRoot, "logs"), paths.DataRoot);
        RemoveOwnedTree(paths.StateRoot, paths.DataRoot);
        RemoveLegacyArtifacts(removeOrphanedRuntime: true);
        RemoveOwnedTree(paths.DataRoot);
        Progress("uninstall", "complete", 100, "SwitchTrade-owned software was removed");
    }

    internal async Task VerifySoftwareAsync(CancellationToken cancellationToken)
    {
        var status = await InspectAsync(cancellationToken);
        if (!status.SoftwareReady || status.ActiveRuntime is null || status.ReleaseId is null)
            throw ProvisionerException.State("SOFTWARE_NOT_READY", "The active SwitchTrade runtime is incomplete.");
        await health.CheckAsync(status.ActiveRuntime, status.ReleaseId, status.ControlContract!, cancellationToken);
    }

    private async Task ReplaceAsync(string action, ReleaseManifest manifest, string packageRoot,
        ActiveRuntime? previous, CancellationToken cancellationToken)
    {
        using var operationLock = AcquireLock();
        ValidateHost(manifest);
        var version = await wsl.VersionAsync(cancellationToken);
        if (version < Version.Parse(manifest.MinimumWslVersion))
            throw ProvisionerException.Wsl("WSL_VERSION_UNSUPPORTED",
                $"WSL {manifest.MinimumWslVersion} or newer is required; found {version}.");
        EnsureDiskCapacity(manifest);

        paths.Ensure();
        Directory.CreateDirectory(paths.RuntimeRoot);
        Directory.CreateDirectory(paths.LogRoot);
        var operation = Guid.NewGuid();
        var name = RuntimeName(manifest.ReleaseId, operation);
        var location = Path.Combine(paths.RuntimeRoot, name);
        var runtime = manifest.PayloadPath(packageRoot, "runtime");
        var journal = new OperationJournal(1, operation, action, manifest.ReleaseId,
            manifest.RuntimeContentId, name, location,
            previous?.ActiveName, false);
        AtomicFile.Write(paths.JournalPath, journal);

        var oldConfig = File.Exists(paths.WslConfigPath) ? File.ReadAllBytes(paths.WslConfigPath) : null;
        var oldKernelState = File.Exists(paths.KernelStatePath) ? File.ReadAllBytes(paths.KernelStatePath) : null;
        var pointerCommitted = false;
        try
        {
            Progress(action, "kernel_configuration", 15, "Installing the verified SwitchTrade kernel");
            new KernelManager(paths).Apply(manifest, packageRoot);
            await wsl.ShutdownAsync(cancellationToken);

            Progress(action, "runtime_install", 35, "Installing a fresh isolated SwitchTrade runtime");
            await wsl.InstallAsync(runtime, name, location, cancellationToken);
            await VerifyOwnedAsync(name, manifest.ReleaseId, manifest.RuntimeContentId, location, cancellationToken);
            await VerifyKernelAsync(name, manifest.Kernel.Release, cancellationToken);

            Progress(action, "software_health", 65, "Checking the local SwitchTrade service");
            await health.CheckAsync(name, manifest.ReleaseId, manifest.ControlContract, cancellationToken);

            var active = new ActiveRuntime(1, manifest.ReleaseId, name, previous?.ActiveName,
                manifest.Kernel.Release, manifest.ControlContract);
            AtomicFile.Write(paths.ActivePath, active);
            pointerCommitted = true;
            AtomicFile.Write(paths.JournalPath, journal with { Committed = true });
            try
            {
                await FinishCommittedCleanupAsync(active, cancellationToken);
            }
            catch (Exception error) when (error is ProvisionerException or IOException or UnauthorizedAccessException)
            {
                Progress(action, "cleanup_pending", 95,
                    $"The new release is active; deferred cleanup will retry during the next Repair ({error.GetType().Name}).");
            }
            Progress(action, "complete", 100, "SwitchTrade software is ready");
        }
        catch
        {
            if (!pointerCommitted)
            {
                await RemoveCandidateBestEffortAsync(journal, manifest, cancellationToken);
                RestoreBytes(paths.WslConfigPath, oldConfig);
                RestoreBytes(paths.KernelStatePath, oldKernelState);
                try { await wsl.ShutdownAsync(cancellationToken); } catch (ProvisionerException) { }
                if (File.Exists(paths.JournalPath)) File.Delete(paths.JournalPath);
            }
            throw;
        }
    }

    private async Task VerifyKernelAsync(string name, string expectedRelease,
        CancellationToken cancellationToken)
    {
        var result = await wsl.RunAsync(name, ["uname", "-r"], TimeSpan.FromSeconds(30),
            cancellationToken);
        if (result.ExitCode != 0 || !result.Output.Equals(expectedRelease, StringComparison.Ordinal))
            throw ProvisionerException.Kernel("KERNEL_RUNTIME_MISMATCH",
                $"The SwitchTrade runtime booted kernel '{result.Output}' instead of '{expectedRelease}'.");
    }

    private async Task RecoverInterruptedAsync(ReleaseManifest manifest, CancellationToken cancellationToken)
    {
        var journal = AtomicFile.Read<OperationJournal>(paths.JournalPath);
        if (journal is null) return;
        var active = AtomicFile.Read<ActiveRuntime>(paths.ActivePath);
        if (active is not null && active.ActiveName == journal.CandidateName)
        {
            await FinishCommittedCleanupAsync(active, cancellationToken);
            return;
        }
        if (journal.Committed)
            throw ProvisionerException.State("JOURNAL_COMMIT_INCONSISTENT",
                "The committed setup journal does not match the active runtime.",
                "Contact SwitchTrade support");
        await RemoveCandidateBestEffortAsync(journal, manifest, cancellationToken);
        File.Delete(paths.JournalPath);
    }

    private async Task FinishCommittedCleanupAsync(ActiveRuntime active,
        CancellationToken cancellationToken)
    {
        if (active.PreviousName is not null)
            await RemoveOwnedRuntimeAsync(active.PreviousName, null, null, null, cancellationToken);
        else if (await LegacyExistsAsync(cancellationToken))
            await RemoveLegacyAsync(cancellationToken);
        await RemoveOrphanedOwnedRuntimesAsync(active.ActiveName, cancellationToken);
        RemoveLegacyArtifacts(removeOrphanedRuntime: true);
        AtomicFile.Write(paths.ActivePath, active with { PreviousName = null });
        if (File.Exists(paths.JournalPath)) File.Delete(paths.JournalPath);
    }

    private async Task RemoveCandidateBestEffortAsync(OperationJournal journal, ReleaseManifest manifest,
        CancellationToken cancellationToken)
    {
        if (journal.CandidateName is null || journal.CandidateLocation is null) return;
        var contentId = journal.RuntimeContentId;
        if (string.IsNullOrWhiteSpace(contentId))
        {
            if (!journal.ReleaseId.Equals(manifest.ReleaseId, StringComparison.Ordinal) ||
                string.IsNullOrWhiteSpace(manifest.RuntimeContentId))
                throw ProvisionerException.State("JOURNAL_IDENTITY_INCOMPLETE",
                    "The interrupted runtime has no verifiable payload identity.",
                    "Contact SwitchTrade support");
            contentId = manifest.RuntimeContentId;
        }
        await RemoveOwnedRuntimeAsync(journal.CandidateName, journal.ReleaseId,
            contentId, journal.CandidateLocation, cancellationToken);
    }

    private async Task<bool> LegacyExistsAsync(CancellationToken cancellationToken) =>
        wsl.Registration("SwitchTrade") is not null ||
        (await wsl.NamesAsync(cancellationToken)).Contains("SwitchTrade");

    private void RemoveLegacyArtifacts(bool removeOrphanedRuntime)
    {
        var transactionPath = Path.Combine(paths.DataRoot, "setup-transaction.json");
        string? orphanedRuntime = null;
        if (removeOrphanedRuntime && File.Exists(transactionPath))
        {
            try
            {
                using var document = JsonDocument.Parse(File.ReadAllText(transactionPath));
                if (document.RootElement.TryGetProperty("distro_base_path", out var property))
                {
                    var recorded = property.GetString();
                    var expected = Path.Combine(paths.DataRoot, "wsl");
                    if (recorded is not null && PathEquals(recorded, expected)) orphanedRuntime = expected;
                }
            }
            catch (JsonException) { }
        }

        if (orphanedRuntime is not null) RemoveOwnedTree(orphanedRuntime, paths.DataRoot);
        RemoveOwnedTree(Path.Combine(paths.DataRoot, "recovery"), paths.DataRoot);
        foreach (var name in new[] { "setup-transaction.json", "setup-resume.json", "kernel-state.json" })
        {
            var path = Path.Combine(paths.DataRoot, name);
            if (File.Exists(path)) File.Delete(path);
        }
    }

    internal static string RuntimeName(string releaseId, Guid generation)
    {
        const string prefix = "SwitchTrade-beta-";
        var suffix = "-" + generation.ToString("N");
        var release = releaseId.StartsWith("beta-", StringComparison.OrdinalIgnoreCase)
            ? releaseId[5..] : releaseId;
        release = UnsafeName().Replace(release, "-").Trim('-');
        if (release.Length == 0) release = "release";
        var capacity = 63 - prefix.Length - suffix.Length;
        if (release.Length > capacity) release = release[..capacity].TrimEnd('-');
        return prefix + release + suffix;
    }

    private async Task RemoveLegacyAsync(CancellationToken cancellationToken)
    {
        await VerifyLegacyOwnedAsync(cancellationToken);
        await wsl.TerminateAsync("SwitchTrade", cancellationToken);
        await wsl.UnregisterAsync("SwitchTrade", cancellationToken);
    }

    private async Task VerifyLegacyOwnedAsync(CancellationToken cancellationToken)
    {
        var registration = wsl.Registration("SwitchTrade") ??
            throw ProvisionerException.State("LEGACY_OWNERSHIP_AMBIGUOUS", "The legacy SwitchTrade registration has no readable location.", "Contact SwitchTrade support");
        var legacyTransaction = Path.Combine(paths.DataRoot, "setup-transaction.json");
        if (!File.Exists(legacyTransaction))
            throw ProvisionerException.State("LEGACY_OWNERSHIP_AMBIGUOUS", "The legacy runtime has no ownership transaction.", "Contact SwitchTrade support");
        JsonDocument transaction;
        try { transaction = JsonDocument.Parse(File.ReadAllText(legacyTransaction)); }
        catch (JsonException)
        {
            throw ProvisionerException.State("LEGACY_TRANSACTION_INVALID",
                "The legacy ownership transaction is malformed.", "Contact SwitchTrade support");
        }
        string? installId;
        using (transaction)
        {
            if (!transaction.RootElement.TryGetProperty("distro_base_path", out var recorded) ||
                !PathEquals(registration.BasePath, recorded.GetString()) ||
                !transaction.RootElement.TryGetProperty("install_id", out var installProperty) ||
                string.IsNullOrWhiteSpace(installId = installProperty.GetString()))
                throw ProvisionerException.State("LEGACY_OWNERSHIP_AMBIGUOUS", "The legacy runtime location or install identity does not match its ownership transaction.", "Contact SwitchTrade support");
        }
        var markerResult = await wsl.RunAsync("SwitchTrade", ["cat", "/etc/switchtrade-distro.json"], TimeSpan.FromSeconds(20), cancellationToken);
        JsonDocument? marker = null;
        try { if (markerResult.ExitCode == 0) marker = JsonDocument.Parse(markerResult.Output); }
        catch (JsonException) { }
        using (marker)
        {
            var root = marker?.RootElement;
            if (root is null ||
                !root.Value.TryGetProperty("schema", out var schema) || schema.GetInt32() != 2 ||
                !root.Value.TryGetProperty("owner", out var owner) || owner.GetString() != "switchtrade-installer" ||
                !root.Value.TryGetProperty("product", out var product) || product.GetString() != "SwitchTrade" ||
                !root.Value.TryGetProperty("install_id", out var markerInstall) || markerInstall.GetString() != installId)
                throw ProvisionerException.State("LEGACY_OWNERSHIP_AMBIGUOUS", "The legacy runtime marker is not owned by this SwitchTrade installation.", "Contact SwitchTrade support");
        }
    }

    private async Task RemoveOrphanedOwnedRuntimesAsync(string activeName,
        CancellationToken cancellationToken)
    {
        var candidates = (await wsl.NamesAsync(cancellationToken))
            .Where(name => name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal) &&
                !name.Equals(activeName, StringComparison.OrdinalIgnoreCase))
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (Directory.Exists(paths.RuntimeRoot))
        {
            foreach (var directory in Directory.EnumerateDirectories(paths.RuntimeRoot))
            {
                var name = Path.GetFileName(directory);
                if (name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal) &&
                    !name.Equals(activeName, StringComparison.OrdinalIgnoreCase))
                    candidates.Add(name);
            }
        }
        foreach (var candidate in candidates)
            await RemoveOwnedRuntimeAsync(candidate, null, null, null, cancellationToken);
    }

    private async Task RemoveOwnedRuntimeAsync(string name, string? expectedRelease,
        string? expectedPayload, string? expectedLocation, CancellationToken cancellationToken)
    {
        expectedLocation ??= Path.Combine(paths.RuntimeRoot, name);
        var registration = wsl.Registration(name);
        if (registration is null)
        {
            if ((await wsl.NamesAsync(cancellationToken)).Contains(name))
                throw ProvisionerException.State("RUNTIME_REGISTRATION_MISSING",
                    $"WSL lists a SwitchTrade runtime without a readable registration: {name}",
                    "Run Setup Repair");
            RemoveOwnedTree(expectedLocation, paths.RuntimeRoot);
            return;
        }
        await VerifyOwnedAsync(name, expectedRelease, expectedPayload, expectedLocation, cancellationToken);
        await wsl.TerminateAsync(name, cancellationToken);
        await wsl.UnregisterAsync(name, cancellationToken);
        for (var attempt = 0; attempt < 5; attempt++)
        {
            if (wsl.Registration(name) is null &&
                !(await wsl.NamesAsync(cancellationToken)).Contains(name))
            {
                RemoveOwnedTree(expectedLocation, paths.RuntimeRoot);
                return;
            }
            if (attempt < 4) await Task.Delay(TimeSpan.FromMilliseconds(100), cancellationToken);
        }
        throw ProvisionerException.Wsl("WSL_UNREGISTER_INCOMPLETE",
            $"WSL did not fully remove the verified SwitchTrade runtime: {name}");
    }

    private async Task VerifyOwnedAsync(string name, string? expectedRelease, string? expectedPayload,
        string? expectedLocation, CancellationToken cancellationToken)
    {
        if (!name.StartsWith("SwitchTrade-beta-", StringComparison.Ordinal))
            throw ProvisionerException.State("RUNTIME_OWNERSHIP_INVALID", $"Refusing unowned WSL runtime: {name}", "Contact SwitchTrade support");
        var registration = wsl.Registration(name) ??
            throw ProvisionerException.State("RUNTIME_REGISTRATION_MISSING", $"WSL registration is missing: {name}");
        var root = Path.GetFullPath(paths.RuntimeRoot).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!Path.GetFullPath(registration.BasePath).StartsWith(root, StringComparison.OrdinalIgnoreCase) ||
            (expectedLocation is not null && !PathEquals(registration.BasePath, expectedLocation)))
            throw ProvisionerException.State("RUNTIME_LOCATION_UNOWNED", $"Refusing WSL runtime outside the SwitchTrade runtime root: {name}", "Contact SwitchTrade support");
        var result = await wsl.RunAsync(name, ["cat", "/etc/switchtrade-distro.json"], TimeSpan.FromSeconds(20), cancellationToken);
        RuntimeOwnership? marker = null;
        try { marker = JsonSerializer.Deserialize<RuntimeOwnership>(result.Output, Contract.Json); }
        catch (JsonException) { }
        if (result.ExitCode != 0 || marker is null || marker.Schema != 1 || marker.Owner != "switchtrade-provisioner" || marker.Product != "SwitchTrade" ||
            (expectedRelease is not null && marker.ReleaseId != expectedRelease) ||
            (expectedPayload is not null && marker.PayloadSha256 != expectedPayload))
            throw ProvisionerException.State("RUNTIME_OWNERSHIP_INVALID", $"The WSL runtime marker is invalid: {name}", "Contact SwitchTrade support");
    }

    private FileLockLease AcquireLock()
    {
        paths.Ensure();
        var identity = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
            System.Text.Encoding.UTF8.GetBytes(paths.DataRoot))).ToLowerInvariant()[..20];
        var lockRoot = Path.Combine(Path.GetTempPath(), "SwitchTradeProvisionerLocks");
        Directory.CreateDirectory(lockRoot);
        try
        {
            var stream = new FileStream(Path.Combine(lockRoot, identity + ".lock"),
                FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None, 1,
                FileOptions.DeleteOnClose);
            return new FileLockLease(stream);
        }
        catch (IOException)
        {
            throw ProvisionerException.State("PROVISIONER_BUSY",
                "Another SwitchTrade setup operation is running.", "Wait and try again");
        }
    }

    private static void ValidateHost(ReleaseManifest manifest)
    {
        if (!OperatingSystem.IsWindows() || !Environment.Is64BitOperatingSystem)
            throw ProvisionerException.State("HOST_ARCHITECTURE_UNSUPPORTED", "SwitchTrade requires 64-bit Windows.", "Use a supported x64 PC");
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, manifest.MinimumWindowsBuild))
            throw ProvisionerException.State("WINDOWS_BUILD_UNSUPPORTED", $"Windows build {manifest.MinimumWindowsBuild} or newer is required.", "Update Windows");
    }

    private void EnsureDiskCapacity(ReleaseManifest manifest)
    {
        if (!manifest.Payloads.TryGetValue("runtime", out var runtime)) return;
        var root = Path.GetPathRoot(paths.DataRoot) ??
            throw ProvisionerException.State("DATA_VOLUME_INVALID", "SwitchTrade storage has no valid volume.");
        var drive = new DriveInfo(root);
        var required = Math.Max(4L * 1024 * 1024 * 1024, checked(runtime.Size * 4));
        if (drive.AvailableFreeSpace < required)
            throw ProvisionerException.State("DISK_SPACE_INSUFFICIENT",
                $"SwitchTrade needs at least {required / (1024 * 1024)} MiB free on {drive.Name}; " +
                $"{drive.AvailableFreeSpace / (1024 * 1024)} MiB is available.",
                "Free disk space and try again");
    }

    private void Progress(string action, string stage, int percent, string message) =>
        emit(new ProvisionerEvent(1, "progress", correlationId, action, stage, percent, Message: message));

    private static bool PathEquals(string left, string? right) => right is not null &&
        Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar).Equals(
            Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar), StringComparison.OrdinalIgnoreCase);

    private static void RestoreBytes(string path, byte[]? bytes)
    {
        if (bytes is null) { if (File.Exists(path)) File.Delete(path); return; }
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, bytes);
    }

    private static void RemoveOwnedTree(string path, string? requiredParent = null)
    {
        if (!Directory.Exists(path)) return;
        var full = Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar);
        if (requiredParent is not null)
        {
            var parent = Path.GetFullPath(requiredParent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            if (!full.StartsWith(parent, StringComparison.OrdinalIgnoreCase))
                throw ProvisionerException.State("DELETE_PATH_UNOWNED", $"Refusing path outside SwitchTrade storage: {full}", "Contact SwitchTrade support");
        }
        if ((File.GetAttributes(full) & FileAttributes.ReparsePoint) != 0)
            throw ProvisionerException.State("DELETE_REPARSE_POINT", $"Refusing reparse-point deletion: {full}", "Contact SwitchTrade support");
        var pending = new Stack<string>();
        pending.Push(full);
        while (pending.Count > 0)
        {
            var directory = pending.Pop();
            foreach (var entry in Directory.EnumerateFileSystemEntries(directory))
            {
                var attributes = File.GetAttributes(entry);
                if ((attributes & FileAttributes.ReparsePoint) != 0)
                    throw ProvisionerException.State("DELETE_REPARSE_POINT",
                        $"Refusing deletion because owned storage contains a reparse point: {entry}",
                        "Contact SwitchTrade support");
                if ((attributes & FileAttributes.Directory) != 0) pending.Push(entry);
            }
        }
        Directory.Delete(full, true);
    }

    private sealed class FileLockLease(FileStream stream) : IDisposable
    {
        public void Dispose() => stream.Dispose();
    }
}
