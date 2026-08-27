using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Cryptography.Pkcs;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using System.Text;
using System.Windows.Forms;
using System.Security.Principal;

namespace SwitchTrade.Setup;

internal static class Program
{
    private const string SetupFailurePrefix = "SWITCHTRADE_SETUP_ERROR: ";
    private const string StructuredFailurePrefix = "SWITCHTRADE_SETUP_FAILURE: ";

    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var requestedAction = args.Select(value => value.ToLowerInvariant()).FirstOrDefault(value =>
            value is "audit" or "install" or "repair" or "update" or "resume" or "rollback" or "uninstall");
        var isAdministrator = new WindowsPrincipal(WindowsIdentity.GetCurrent())
            .IsInRole(WindowsBuiltInRole.Administrator);
        if (requestedAction != "audit" && !isAdministrator)
        {
            if (args.Contains("--elevated", StringComparer.OrdinalIgnoreCase))
            {
                Console.Error.WriteLine("SETUP_ELEVATION_FAILED");
                return 740;
            }
            return RelaunchElevated(args);
        }
        var allowUnsigned = args.Contains("--allow-unsigned-package", StringComparer.OrdinalIgnoreCase);
        bool unsignedPrivateBeta;
        try
        {
            unsignedPrivateBeta = VerifyPackage(AppContext.BaseDirectory, allowUnsigned);
        }
        catch (Exception error)
        {
            if (requestedAction is not null)
            {
                Console.Error.WriteLine(error.Message);
                return 3;
            }
            MessageBox.Show($"SwitchTrade setup stopped before making changes.\n\n{error.Message}",
                "SwitchTrade Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 3;
        }
        if (unsignedPrivateBeta && requestedAction is null && MessageBox.Show(
                "This is an unsigned SwitchTrade private beta. Windows cannot verify its publisher, " +
                "and its checksums do not prove who created it. Continue only if you received this " +
                "package directly from the SwitchTrade project owner.",
                "Unsigned SwitchTrade Private Beta", MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning) != DialogResult.Yes)
            return 0;
        var invokingLocalAppData = DecodeInvokingArgument(args,
            "--invoking-local-app-data-b64=", requireRooted: true) ??
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        var choice = requestedAction is null
            ? SetupDialog.Show(AppContext.BaseDirectory, invokingLocalAppData)
            : null;
        if (requestedAction is null && choice is null) return 0;
        var action = requestedAction ?? choice!.Action.ToLowerInvariant();
        var interactive = requestedAction is null || action == "resume";
        var script = Path.Combine(AppContext.BaseDirectory, "installer", "SwitchTradeSetup.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show("The SwitchTrade setup payload is incomplete.", "SwitchTrade Setup",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }

        var start = new ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-NonInteractive");
        start.ArgumentList.Add("-ExecutionPolicy");
        start.ArgumentList.Add("Bypass");
        start.ArgumentList.Add("-File");
        start.ArgumentList.Add(script);
        start.ArgumentList.Add("-Action");
        start.ArgumentList.Add(char.ToUpperInvariant(action[0]) + action[1..]);
        AddInvokingUserArgument(args, start, "--invoking-user-profile-b64=", "-UserProfileRoot", true);
        AddInvokingUserArgument(args, start, "--invoking-local-app-data-b64=", "-LocalAppDataRoot", true);
        AddInvokingUserArgument(args, start, "--invoking-desktop-b64=", "-DesktopRoot", true);
        AddInvokingUserArgument(args, start, "--invoking-user-sid-b64=", "-InvokingUserSid", false);
        foreach (var option in args)
        {
            if (option == "--purge-distro") start.ArgumentList.Add("-PurgeDistro");
            if (option == "--accept-global-kernel-change") start.ArgumentList.Add("-AcceptGlobalKernelChange");
            if (option == "--accept-prerequisite-changes") start.ArgumentList.Add("-AcceptPrerequisiteChanges");
            if (option == "--accept-vmware-release") start.ArgumentList.Add("-AcceptVmwareRelease");
            if (option == "--defer-hardware-setup") start.ArgumentList.Add("-DeferHardwareSetup");
            if (option == "--no-shortcut") start.ArgumentList.Add("-NoShortcut");
            if (option == "--allow-unsigned-package") start.ArgumentList.Add("-AllowUnsignedPackage");
            if (option.StartsWith("--bus-id=", StringComparison.OrdinalIgnoreCase) &&
                System.Text.RegularExpressions.Regex.IsMatch(option[9..], @"^\d+-\d+$"))
            {
                start.ArgumentList.Add("-BusId");
                start.ArgumentList.Add(option[9..]);
            }
            if (option.StartsWith("--usb-id=", StringComparison.OrdinalIgnoreCase) &&
                System.Text.RegularExpressions.Regex.IsMatch(option[9..], @"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$"))
            {
                start.ArgumentList.Add("-UsbId");
                start.ArgumentList.Add(option[9..]);
            }
            if (option.StartsWith("--usb-instance-id=", StringComparison.OrdinalIgnoreCase) &&
                option[18..].Length is > 0 and <= 512 && !option[18..].Any(char.IsControl))
            {
                start.ArgumentList.Add("-UsbInstanceId");
                start.ArgumentList.Add(option[18..]);
            }
        }
        if (unsignedPrivateBeta && !allowUnsigned) start.ArgumentList.Add("-AllowUnsignedPackage");
        if (choice is not null)
        {
            if (choice.AcceptGlobalKernelChange) start.ArgumentList.Add("-AcceptGlobalKernelChange");
            if (choice.AcceptPrerequisiteChanges) start.ArgumentList.Add("-AcceptPrerequisiteChanges");
            if (choice.AcceptVmwareRelease) start.ArgumentList.Add("-AcceptVmwareRelease");
            if (choice.DeferHardwareSetup) start.ArgumentList.Add("-DeferHardwareSetup");
            if (choice.PurgeDistro) start.ArgumentList.Add("-PurgeDistro");
            if (choice.Radio is not null)
            {
                start.ArgumentList.Add("-BusId");
                start.ArgumentList.Add(choice.Radio.BusId);
                start.ArgumentList.Add("-UsbId");
                start.ArgumentList.Add(choice.Radio.UsbId);
                start.ArgumentList.Add("-UsbInstanceId");
                start.ArgumentList.Add(choice.Radio.InstanceId);
            }
        }
        if (interactive) start.Environment["SWITCHTRADE_SETUP_PROGRESS"] = "1";

        try
        {
            var result = interactive
                ? SetupProgressDialog.Run(start, action)
                : RunHeadless(start);
            var restartRequired = result.ExitCode == 3010;
            var success = result.ExitCode == 0 || restartRequired;
            var message = success ? result.Output.Trim() : result.Error.Trim();
            if (!interactive)
            {
                if (success) Console.Out.WriteLine(message);
                else Console.Error.WriteLine(message);
                return result.ExitCode;
            }
            message = restartRequired
                ? "Restart Windows to let SwitchTrade Setup continue automatically after sign-in."
                : success
                    ? "SwitchTrade setup completed successfully.\n\n" +
                      "You can now delete the extracted setup folder and ZIP. " +
                      "Keep or re-download a setup package only for Update, Repair, Rollback, or Uninstall."
                    : string.IsNullOrWhiteSpace(message)
                        ? "SwitchTrade setup did not complete."
                        : FirstErrorLine(message);
            MessageBox.Show(message, "SwitchTrade Setup", MessageBoxButtons.OK,
                success ? MessageBoxIcon.Information : MessageBoxIcon.Error);
            return result.ExitCode;
        }
        catch (Exception error)
        {
            if (requestedAction is not null)
            {
                Console.Error.WriteLine(error.Message);
                return 1;
            }
            MessageBox.Show(error.Message, "SwitchTrade Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static int RelaunchElevated(string[] args)
    {
        var executable = Environment.ProcessPath ?? throw new InvalidOperationException("SETUP_EXECUTABLE_PATH_MISSING");
        var start = new ProcessStartInfo(executable) { UseShellExecute = true, Verb = "runas" };
        foreach (var argument in args) start.ArgumentList.Add(argument);
        start.ArgumentList.Add("--elevated");
        AddEncoded(start, "--invoking-user-profile-b64=", Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
        AddEncoded(start, "--invoking-local-app-data-b64=", Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData));
        AddEncoded(start, "--invoking-desktop-b64=", Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
        AddEncoded(start, "--invoking-user-sid-b64=", WindowsIdentity.GetCurrent().User?.Value ?? "");
        try
        {
            using var process = Process.Start(start) ?? throw new InvalidOperationException("SETUP_ELEVATION_FAILED");
            process.WaitForExit();
            return process.ExitCode;
        }
        catch (System.ComponentModel.Win32Exception error) when (error.NativeErrorCode == 1223)
        {
            return 1223;
        }
    }

    private static void AddEncoded(ProcessStartInfo start, string prefix, string value) =>
        start.ArgumentList.Add(prefix + Convert.ToBase64String(Encoding.UTF8.GetBytes(value)));

    private static void AddInvokingUserArgument(
        string[] args, ProcessStartInfo start, string prefix, string parameter, bool requireRooted)
    {
        var value = DecodeInvokingArgument(args, prefix, requireRooted);
        if (value is null) return;
        start.ArgumentList.Add(parameter);
        start.ArgumentList.Add(value);
    }

    private static string? DecodeInvokingArgument(string[] args, string prefix, bool requireRooted)
    {
        var encoded = args.LastOrDefault(value => value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase));
        if (encoded is null) return null;
        string value;
        try { value = Encoding.UTF8.GetString(Convert.FromBase64String(encoded[prefix.Length..])); }
        catch (FormatException) { throw new InvalidDataException("INVOKING_USER_CONTEXT_INVALID"); }
        if (string.IsNullOrWhiteSpace(value) || value.Contains('\0') ||
            (requireRooted && !Path.IsPathFullyQualified(value)) ||
            (!requireRooted && !System.Text.RegularExpressions.Regex.IsMatch(value, @"^S-1-5-21-(?:\d+-){3}\d+$")))
            throw new InvalidDataException("INVOKING_USER_CONTEXT_INVALID");
        return requireRooted ? Path.GetFullPath(value) : value;
    }

    private static string FirstErrorLine(string error)
    {
        var lines = error.Replace("\0", "").Split(['\r', '\n'],
            StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
        var structured = lines.LastOrDefault(line =>
            line.StartsWith(StructuredFailurePrefix, StringComparison.Ordinal));
        if (structured is not null)
        {
            try
            {
                using var failure = JsonDocument.Parse(structured[StructuredFailurePrefix.Length..]);
                var root = failure.RootElement;
                var code = root.GetProperty("code").GetString() ?? "SETUP_FAILED";
                var message = root.GetProperty("message").GetString() ?? "SwitchTrade setup did not complete.";
                var stage = root.GetProperty("stage").GetString() ?? "unknown";
                var action = root.GetProperty("action").GetString() ?? "unknown";
                var recovery = root.GetProperty("primary_action").GetString() ?? "Run Setup Repair";
                return $"[{code}] {message}\nStage: {stage}\nAction: {action}\nRecovery: {recovery}";
            }
            catch (JsonException) { }
        }
        var setupFailure = lines.LastOrDefault(line =>
            line.StartsWith(SetupFailurePrefix, StringComparison.Ordinal));
        return setupFailure is null
            ? lines.FirstOrDefault() ?? "SwitchTrade setup did not complete."
            : setupFailure[SetupFailurePrefix.Length..].Trim();
    }

    private static SetupProcessResult RunHeadless(ProcessStartInfo start)
    {
        using var process = Process.Start(start) ?? throw new InvalidOperationException("Setup did not start.");
        var outputTask = process.StandardOutput.ReadToEndAsync();
        var errorTask = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(outputTask, errorTask);
        return new SetupProcessResult(process.ExitCode, outputTask.Result, errorTask.Result);
    }

    private static bool VerifyPackage(string packageRoot, bool allowUnsigned)
    {
        var root = Path.GetFullPath(packageRoot).TrimEnd(Path.DirectorySeparatorChar);
        var manifestPath = Path.Combine(root, "manifest.json");
        var signaturePath = Path.Combine(root, "manifest.json.p7s");
        if (!File.Exists(manifestPath)) throw new InvalidDataException("PACKAGE_MANIFEST_MISSING");
        using var manifest = JsonDocument.Parse(File.ReadAllBytes(manifestPath));
        var document = manifest.RootElement;
        if (!document.TryGetProperty("schema", out var schema) || schema.GetInt32() != 2 ||
            !document.TryGetProperty("artifact_hashes", out var artifacts))
            throw new InvalidDataException("PACKAGE_MANIFEST_UNSUPPORTED");
        var signatureRequired = document.TryGetProperty("signature_required", out var required) &&
                                required.ValueKind == JsonValueKind.True;
        var unsignedPrivateBeta = document.TryGetProperty("unsigned_private_beta", out var beta) &&
                                  beta.ValueKind == JsonValueKind.True;
        if (File.Exists(signaturePath)) VerifySignature(manifestPath, signaturePath);
        else if (signatureRequired || (!allowUnsigned && !unsignedPrivateBeta))
            throw new InvalidDataException(
                "PACKAGE_SIGNATURE_MISSING: obtain a signed release package. Unsigned builds require the explicit internal-test flag.");

        var expected = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var artifact in artifacts.EnumerateObject())
        {
            var relative = artifact.Name.Replace('/', Path.DirectorySeparatorChar);
            if (Path.IsPathRooted(relative) || relative.Split(Path.DirectorySeparatorChar).Contains(".."))
                throw new InvalidDataException($"PACKAGE_PATH_INVALID: {artifact.Name}");
            var fullPath = Path.GetFullPath(Path.Combine(root, relative));
            if (!fullPath.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException($"PACKAGE_PATH_INVALID: {artifact.Name}");
            if (!File.Exists(fullPath)) throw new InvalidDataException($"PACKAGE_ARTIFACT_MISSING: {artifact.Name}");
            var expectedHash = artifact.Value.GetString() ?? "";
            using var artifactStream = File.OpenRead(fullPath);
            var actualHash = Convert.ToHexString(SHA256.HashData(artifactStream)).ToLowerInvariant();
            if (!CryptographicOperations.FixedTimeEquals(
                    Convert.FromHexString(expectedHash), Convert.FromHexString(actualHash)))
                throw new InvalidDataException($"PACKAGE_ARTIFACT_MISMATCH: {artifact.Name}");
            expected[Path.GetRelativePath(root, fullPath)] = expectedHash;
        }
        var actual = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(root, path))
            .Where(path => !path.Equals("manifest.json", StringComparison.OrdinalIgnoreCase) &&
                           !path.Equals("manifest.json.p7s", StringComparison.OrdinalIgnoreCase))
            .ToArray();
        var unexpected = actual.FirstOrDefault(path => !expected.ContainsKey(path));
        if (unexpected is not null) throw new InvalidDataException($"PACKAGE_UNEXPECTED_ARTIFACT: {unexpected}");
        if (actual.Length != expected.Count) throw new InvalidDataException("PACKAGE_ARTIFACT_SET_MISMATCH");
        return unsignedPrivateBeta;
    }

    private static void VerifySignature(string contentPath, string signaturePath)
    {
        var signed = new SignedCms(new ContentInfo(File.ReadAllBytes(contentPath)), detached: true);
        signed.Decode(File.ReadAllBytes(signaturePath));
        signed.CheckSignature(verifySignatureOnly: false);
        if (signed.SignerInfos.Count < 1) throw new CryptographicException("PACKAGE_SIGNATURE_HAS_NO_SIGNER");
        foreach (SignerInfo signer in signed.SignerInfos)
        {
            var certificate = signer.Certificate ?? throw new CryptographicException("PACKAGE_SIGNATURE_CERTIFICATE_MISSING");
            var codeSigning = certificate.Extensions.OfType<X509EnhancedKeyUsageExtension>()
                .SelectMany(extension => extension.EnhancedKeyUsages.Cast<Oid>())
                .Any(usage => usage.Value == "1.3.6.1.5.5.7.3.3");
            if (!codeSigning) throw new CryptographicException("PACKAGE_SIGNATURE_CERTIFICATE_NOT_CODE_SIGNING");
        }
    }
}
