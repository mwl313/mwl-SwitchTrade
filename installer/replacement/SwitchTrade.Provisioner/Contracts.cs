using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace SwitchTrade.Provisioner;

internal static partial class Contract
{
    internal static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNameCaseInsensitive = false,
    };

    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$", RegexOptions.CultureInvariant)]
    internal static partial Regex SafeId();

    internal static string HashFile(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}

internal sealed record PayloadDescriptor(
    [property: JsonPropertyName("path")] string Path,
    [property: JsonPropertyName("size")] long Size,
    [property: JsonPropertyName("sha256")] string Sha256);

internal sealed record KernelDescriptor(
    [property: JsonPropertyName("release")] string Release,
    [property: JsonPropertyName("primary_driver")] string PrimaryDriver,
    [property: JsonPropertyName("driver_profiles")] string[] DriverProfiles);

internal sealed record ReleaseManifest(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("release_id")] string ReleaseId,
    [property: JsonPropertyName("version")] string Version,
    [property: JsonPropertyName("architecture")] string Architecture,
    [property: JsonPropertyName("minimum_windows_build")] int MinimumWindowsBuild,
    [property: JsonPropertyName("minimum_wsl_version")] string MinimumWslVersion,
    [property: JsonPropertyName("control_contract")] string ControlContract,
    [property: JsonPropertyName("relay_url")] string RelayUrl,
    [property: JsonPropertyName("runtime_content_id")] string RuntimeContentId,
    [property: JsonPropertyName("kernel")] KernelDescriptor Kernel,
    [property: JsonPropertyName("payloads")] Dictionary<string, PayloadDescriptor> Payloads)
{
    internal static ReleaseManifest LoadVerified(string packageRoot)
    {
        var root = Path.GetFullPath(packageRoot);
        var path = Path.Combine(root, "release-manifest.json");
        if (!File.Exists(path))
            throw ProvisionerException.Integrity("RELEASE_MANIFEST_MISSING", "The release manifest is missing.");

        ReleaseManifest value;
        try
        {
            value = JsonSerializer.Deserialize<ReleaseManifest>(File.ReadAllText(path), Contract.Json)
                ?? throw new JsonException("Manifest is empty.");
        }
        catch (JsonException error)
        {
            throw ProvisionerException.Integrity("RELEASE_MANIFEST_INVALID", error.Message);
        }

        if (value.Schema != 1 || !Contract.SafeId().IsMatch(value.ReleaseId) ||
            value.Architecture != "x64" || value.MinimumWindowsBuild < 19045 ||
            !System.Version.TryParse(value.MinimumWslVersion, out _) ||
            value.ControlContract != "app-readiness.v1" ||
            !Regex.IsMatch(value.RuntimeContentId, "^[0-9a-f]{64}$", RegexOptions.CultureInvariant) ||
            !Uri.TryCreate(value.RelayUrl, UriKind.Absolute, out var relay) || relay.Scheme != Uri.UriSchemeHttps)
            throw ProvisionerException.Integrity("RELEASE_MANIFEST_INVALID", "Release metadata violates the v1 contract.");

        foreach (var (name, payload) in value.Payloads)
        {
            if (string.IsNullOrWhiteSpace(name) || payload.Size <= 0 ||
                !Regex.IsMatch(payload.Sha256, "^[0-9a-f]{64}$", RegexOptions.CultureInvariant))
                throw ProvisionerException.Integrity("RELEASE_MANIFEST_INVALID", $"Payload metadata is invalid: {name}");
            var full = Path.GetFullPath(Path.Combine(root, payload.Path));
            if (!full.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw ProvisionerException.Integrity("PAYLOAD_PATH_ESCAPE", $"Payload escapes the package: {name}");
            var info = new FileInfo(full);
            if (!info.Exists || info.Length != payload.Size || Contract.HashFile(full) != payload.Sha256)
                throw ProvisionerException.Integrity("PAYLOAD_INTEGRITY_FAILED", $"Payload verification failed: {name}");
        }
        return value;
    }

    internal string PayloadPath(string packageRoot, string key)
    {
        if (!Payloads.TryGetValue(key, out var value))
            throw ProvisionerException.Integrity("REQUIRED_PAYLOAD_MISSING", $"Required payload is absent: {key}");
        return Path.GetFullPath(Path.Combine(packageRoot, value.Path));
    }
}

internal sealed record ActiveRuntime(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("release_id")] string ReleaseId,
    [property: JsonPropertyName("active_runtime")] string ActiveName,
    [property: JsonPropertyName("previous_runtime")] string? PreviousName,
    [property: JsonPropertyName("kernel_release")] string KernelRelease,
    [property: JsonPropertyName("control_contract")] string ControlContract);

internal sealed record OperationJournal(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("operation_id")] Guid OperationId,
    [property: JsonPropertyName("action")] string Action,
    [property: JsonPropertyName("release_id")] string ReleaseId,
    [property: JsonPropertyName("runtime_content_id")] string? RuntimeContentId,
    [property: JsonPropertyName("candidate_runtime")] string? CandidateName,
    [property: JsonPropertyName("candidate_location")] string? CandidateLocation,
    [property: JsonPropertyName("previous_runtime")] string? PreviousName,
    [property: JsonPropertyName("committed")] bool Committed);

internal sealed record RuntimeOwnership(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("owner")] string Owner,
    [property: JsonPropertyName("product")] string Product,
    [property: JsonPropertyName("release_id")] string ReleaseId,
    [property: JsonPropertyName("payload_sha256")] string PayloadSha256);

internal sealed record KernelState(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("original_exists")] bool OriginalExists,
    [property: JsonPropertyName("original_backup")] string OriginalBackup,
    [property: JsonPropertyName("original_sha256")] string OriginalSha256,
    [property: JsonPropertyName("installed_kernel")] string InstalledKernel,
    [property: JsonPropertyName("installed_kernel_sha256")] string InstalledKernelSha256,
    [property: JsonPropertyName("kernel_release")] string KernelRelease,
    [property: JsonPropertyName("applied_kernel_value")] string AppliedKernelValue);

internal sealed record ProvisionerStatus(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("state")] string State,
    [property: JsonPropertyName("software_ready")] bool SoftwareReady,
    [property: JsonPropertyName("release_id")] string? ReleaseId,
    [property: JsonPropertyName("active_runtime")] string? ActiveRuntime,
    [property: JsonPropertyName("kernel_release")] string? KernelRelease,
    [property: JsonPropertyName("control_contract")] string? ControlContract,
    [property: JsonPropertyName("recovery_action")] string? RecoveryAction);

internal sealed record ProvisionerEvent(
    [property: JsonPropertyName("schema")] int Schema,
    [property: JsonPropertyName("type")] string Type,
    [property: JsonPropertyName("correlation_id")] Guid CorrelationId,
    [property: JsonPropertyName("action")] string? Action,
    [property: JsonPropertyName("stage")] string Stage,
    [property: JsonPropertyName("percent")] int? Percent = null,
    [property: JsonPropertyName("status")] string? Status = null,
    [property: JsonPropertyName("software_ready")] bool? SoftwareReady = null,
    [property: JsonPropertyName("code")] string? Code = null,
    [property: JsonPropertyName("message")] string? Message = null,
    [property: JsonPropertyName("recoverable")] bool? Recoverable = null,
    [property: JsonPropertyName("primary_action")] string? PrimaryAction = null);

internal sealed class ProvisionerException : Exception
{
    internal ProvisionerException(string code, string stage, string message, bool recoverable, string primaryAction, int exitCode)
        : base(message)
    {
        Code = code;
        Stage = stage;
        Recoverable = recoverable;
        PrimaryAction = primaryAction;
        ExitCode = exitCode;
    }

    internal string Code { get; }
    internal string Stage { get; }
    internal bool Recoverable { get; }
    internal string PrimaryAction { get; }
    internal int ExitCode { get; }

    internal static ProvisionerException Integrity(string code, string message) =>
        new(code, "package_integrity", message, false, "Download a new SwitchTrade Setup package", 30);
    internal static ProvisionerException State(string code, string message, string action = "Run Setup Repair") =>
        new(code, "state_inspection", message, true, action, 10);
    internal static ProvisionerException Wsl(string code, string message, bool recoverable = true) =>
        new(code, "wsl_runtime", message, recoverable, recoverable ? "Run Setup Repair" : "Contact SwitchTrade support", 40);
    internal static ProvisionerException Kernel(string code, string message, bool recoverable = true) =>
        new(code, "kernel_configuration", message, recoverable, recoverable ? "Run Setup Repair" : "Contact SwitchTrade support", 50);
}
