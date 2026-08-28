using System.Security.Principal;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace SwitchTrade.Provisioner;

internal static partial class HardwareAuthorization
{
    [GeneratedRegex("^[0-9A-Fa-f]{4}:[0-9A-Fa-f]{4}$", RegexOptions.CultureInvariant)]
    private static partial Regex UsbIdPattern();

    [GeneratedRegex("VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex InstanceUsbIdPattern();

    internal static bool IsAdministrator()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return new WindowsPrincipal(identity).IsInRole(WindowsBuiltInRole.Administrator);
    }

    internal static async Task AuthorizeAsync(
        string instanceId,
        string usbId,
        Func<IReadOnlyList<string>, CancellationToken, Task<ProcessResult>> run,
        Func<bool> isAdministrator,
        CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(instanceId) || instanceId.Length > 512 ||
            !UsbIdPattern().IsMatch(usbId))
            throw Failure("ADAPTER_IDENTITY_INVALID", "The selected adapter identity is invalid.",
                false, "Select the adapter again", 61);

        var expectedUsbId = usbId.ToLowerInvariant();
        var state = await ReadStateAsync(run, cancellationToken);
        var device = FindExact(state, instanceId, expectedUsbId);
        if (device.Shared) return;
        if (!isAdministrator())
            throw Failure("ADAPTER_AUTHORIZATION_REQUIRES_ADMIN",
                "Windows administrator approval is required to authorize this adapter.",
                true, "Approve the Windows prompt and try again", 62);

        var bind = await run(["bind", "--busid", device.BusId], cancellationToken);
        if (bind.ExitCode != 0)
            throw Failure("ADAPTER_BIND_FAILED", Useful(bind), true,
                "Reconnect the adapter and try again", 63);

        var verified = FindExact(await ReadStateAsync(run, cancellationToken), instanceId, expectedUsbId);
        if (!verified.Shared)
            throw Failure("ADAPTER_BIND_VERIFICATION_FAILED",
                "Windows did not confirm that the selected adapter is shared.",
                true, "Reconnect the adapter and try again", 64);
    }

    private static async Task<UsbipdState> ReadStateAsync(
        Func<IReadOnlyList<string>, CancellationToken, Task<ProcessResult>> run,
        CancellationToken cancellationToken)
    {
        ProcessResult result;
        try { result = await run(["state"], cancellationToken); }
        catch (System.ComponentModel.Win32Exception error)
        {
            throw Failure("USBIPD_UNAVAILABLE", error.Message, true, "Run Setup Repair", 65);
        }
        if (result.ExitCode != 0)
            throw Failure("USBIPD_STATE_FAILED", Useful(result), true, "Run Setup Repair", 66);
        try
        {
            return JsonSerializer.Deserialize<UsbipdState>(result.Output, Contract.Json) ??
                   throw new JsonException("Empty usbipd state.");
        }
        catch (JsonException error)
        {
            throw Failure("USBIPD_STATE_INVALID", error.Message, true, "Run Setup Repair", 67);
        }
    }

    private static ResolvedDevice FindExact(UsbipdState state, string instanceId, string expectedUsbId)
    {
        var matches = state.Devices.Where(device =>
            string.Equals(device.InstanceId, instanceId, StringComparison.OrdinalIgnoreCase)).ToArray();
        if (matches.Length != 1)
            throw Failure("ADAPTER_DISCONNECTED",
                "The selected adapter is no longer connected to Windows.",
                true, "Reconnect and select the adapter again", 68);
        var selected = matches[0];
        var identity = InstanceUsbIdPattern().Match(selected.InstanceId ?? "");
        var actualUsbId = identity.Success
            ? $"{identity.Groups[1].Value}:{identity.Groups[2].Value}".ToLowerInvariant()
            : "";
        if (actualUsbId != expectedUsbId || string.IsNullOrWhiteSpace(selected.BusId))
            throw Failure("ADAPTER_IDENTITY_CHANGED",
                "The selected USB identity changed before Windows authorization.",
                true, "Select the adapter again", 69);
        return new ResolvedDevice(
            selected.BusId,
            !string.IsNullOrWhiteSpace(selected.PersistedGuid) ||
            !string.IsNullOrWhiteSpace(selected.StubInstanceId));
    }

    private static string Useful(ProcessResult result) =>
        string.IsNullOrWhiteSpace(result.Error) ? result.Output : result.Error;

    private static ProvisionerException Failure(
        string code, string message, bool recoverable, string action, int exitCode) =>
        new(code, "hardware_share", message, recoverable, action, exitCode);

    private sealed record ResolvedDevice(string BusId, bool Shared);
    private sealed record UsbipdState(
        [property: JsonPropertyName("Devices")] IReadOnlyList<UsbipdDevice> Devices);
    private sealed record UsbipdDevice(
        [property: JsonPropertyName("BusId")] string? BusId,
        [property: JsonPropertyName("InstanceId")] string? InstanceId,
        [property: JsonPropertyName("PersistedGuid")] string? PersistedGuid,
        [property: JsonPropertyName("StubInstanceId")] string? StubInstanceId);
}
