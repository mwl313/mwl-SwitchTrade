using System.Text.Json;
using System.Text.RegularExpressions;

namespace SwitchTrade.Provisioner;

internal static class Program
{
    private static async Task<int> Main(string[] args)
    {
        var correlationId = Guid.NewGuid();
        var command = args.FirstOrDefault()?.ToLowerInvariant() ?? "";
        var json = args.Contains("--json", StringComparer.OrdinalIgnoreCase) || command == "status";
        var burn = args.Contains("--burn", StringComparer.OrdinalIgnoreCase);
        string? externalLog = null;
        ProvisionerPaths? paths = null;
        void Emit(ProvisionerEvent value)
        {
            var text = JsonSerializer.Serialize(value, Contract.Json);
            Console.Out.WriteLine(text.Replace(Environment.NewLine, "", StringComparison.Ordinal));
            if (paths is not null && command != "uninstall") ProvisionerLog.Write(paths, value);
            if (paths is not null && externalLog is not null) ProvisionerLog.Write(paths, value, externalLog);
        }
        try
        {
            externalLog = Option(args, "--log");
            if (command is not ("inspect" or "install" or "repair" or "uninstall" or "verify-software" or "status"))
                throw new ProvisionerException("USAGE", "arguments",
                    "Usage: SwitchTradeProvisioner <inspect|install|repair|uninstall|verify-software|status --json> [--package-root PATH] [--log PATH]", false, "Use a supported Setup package", 2);
            var packageRoot = Option(args, "--package-root") ?? AppContext.BaseDirectory;
            var dataRoot = Option(args, "--data-root");
            var userProfile = Option(args, "--user-profile");
            var kernelRoot = Option(args, "--kernel-root");
            if ((dataRoot is not null || userProfile is not null || kernelRoot is not null) &&
                Environment.GetEnvironmentVariable("SWITCHTRADE_PROVISIONER_TEST_ROOTS") != "1")
                throw new ProvisionerException("TEST_ROOT_OVERRIDE_DENIED", "arguments",
                    "Custom data and profile roots are available only to the isolated test harness.",
                    false, "Remove the custom root arguments", 2);
            paths = new ProvisionerPaths(dataRoot, userProfile, kernelRoot);
            var wsl = new WslPlatform();
            var engine = new ProvisioningEngine(paths, wsl, new WslRuntimeHealth(wsl), correlationId, Emit);
            switch (command)
            {
                case "status":
                case "inspect":
                    Console.Out.WriteLine(JsonSerializer.Serialize(await engine.InspectAsync(CancellationToken.None), Contract.Json));
                    return 0;
                case "install":
                    await engine.InstallAsync(ReleaseManifest.LoadVerified(packageRoot), packageRoot, CancellationToken.None);
                    break;
                case "repair":
                    await engine.RepairAsync(ReleaseManifest.LoadVerified(packageRoot), packageRoot, CancellationToken.None);
                    break;
                case "uninstall":
                    await engine.UninstallAsync(CancellationToken.None);
                    break;
                case "verify-software":
                    await engine.VerifySoftwareAsync(CancellationToken.None);
                    break;
            }
            var removed = command == "uninstall";
            Emit(new ProvisionerEvent(1, "result", correlationId, command, "complete", 100,
                "succeeded", !removed, Message: removed
                    ? "SwitchTrade-owned software was removed."
                    : "SwitchTrade software is ready."));
            return 0;
        }
        catch (ProvisionerException error)
        {
            var value = new ProvisionerEvent(1, "error", correlationId, command, error.Stage,
                Status: "failed", Code: error.Code, Message: error.Message,
                Recoverable: error.Recoverable, PrimaryAction: error.PrimaryAction);
            if (paths is not null && command == "uninstall") ProvisionerLog.Write(paths, value);
            if (json) Emit(value);
            else Console.Error.WriteLine($"[{error.Code}] {error.Message}{Environment.NewLine}Recovery: {error.PrimaryAction}{Environment.NewLine}Correlation: {correlationId}");
            return burn ? 1603 : error.ExitCode;
        }
        catch (Exception error)
        {
            var value = new ProvisionerEvent(1, "error", correlationId, command, "unexpected",
                Status: "failed", Code: "PROVISIONER_UNEXPECTED", Message: error.Message,
                Recoverable: true, PrimaryAction: "Run Setup Repair");
            if (paths is not null && command == "uninstall") ProvisionerLog.Write(paths, value);
            if (json) Emit(value); else Console.Error.WriteLine($"[PROVISIONER_UNEXPECTED] {error.Message}{Environment.NewLine}Correlation: {correlationId}");
            return burn ? 1603 : 70;
        }
    }

    private static string? Option(string[] args, string name)
    {
        for (var index = 0; index < args.Length; index++)
            if (args[index].Equals(name, StringComparison.OrdinalIgnoreCase))
                return index + 1 < args.Length ? args[index + 1] : throw new ProvisionerException(
                    "USAGE", "arguments", $"{name} requires a value.", false, "Use a supported Setup package", 2);
        return null;
    }
}

internal static partial class ProvisionerLog
{
    [GeneratedRegex("(?i)(authorization|token|secret|password)\\s*[:=]\\s*[^\\s,;]+",
        RegexOptions.CultureInvariant)]
    private static partial Regex SecretPattern();

    internal static void Write(ProvisionerPaths paths, ProvisionerEvent value, string? destination = null)
    {
        try
        {
            var path = destination ?? Path.Combine(paths.LogRoot, value.CorrelationId.ToString("N") + ".jsonl");
            if (!Path.IsPathFullyQualified(path)) return;
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var message = Sanitize(value.Message, paths);
            var action = Sanitize(value.PrimaryAction, paths);
            var safe = value with { Message = message, PrimaryAction = action };
            File.AppendAllText(path, JsonSerializer.Serialize(safe, Contract.Json) + Environment.NewLine);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            // Diagnostics must never replace the operation's real result.
        }
    }

    private static string? Sanitize(string? value, ProvisionerPaths paths)
    {
        if (value is null) return null;
        return SecretPattern().Replace(value
            .Replace(paths.UserProfile, "%USERPROFILE%", StringComparison.OrdinalIgnoreCase)
            .Replace(paths.KernelRoot, "%SWITCHTRADE_KERNEL%", StringComparison.OrdinalIgnoreCase)
            .Replace(paths.DataRoot, "%SWITCHTRADE_DATA%", StringComparison.OrdinalIgnoreCase),
            "$1=[redacted]");
    }
}
