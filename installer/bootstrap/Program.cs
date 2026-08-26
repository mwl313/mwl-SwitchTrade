using System.Diagnostics;
using System.Security.Cryptography;
using System.Security.Cryptography.Pkcs;
using System.Security.Cryptography.X509Certificates;
using System.Text.Json;
using System.Windows.Forms;

namespace SwitchTrade.Setup;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var requestedAction = args.Select(value => value.ToLowerInvariant()).FirstOrDefault(value =>
            value is "audit" or "install" or "repair" or "update" or "resume" or "rollback" or "uninstall");
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
        var choice = requestedAction is null ? SetupDialog.Show(AppContext.BaseDirectory) : null;
        if (requestedAction is null && choice is null) return 0;
        var action = requestedAction ?? choice!.Action.ToLowerInvariant();
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
            }
        }

        try
        {
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Setup did not start.");
            var outputTask = process.StandardOutput.ReadToEndAsync();
            var errorTask = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            Task.WaitAll(outputTask, errorTask);
            var restartRequired = process.ExitCode == 3010;
            var success = process.ExitCode == 0 || restartRequired;
            var message = success ? outputTask.Result.Trim() : errorTask.Result.Trim();
            if (requestedAction is not null)
            {
                if (success) Console.Out.WriteLine(message);
                else Console.Error.WriteLine(message);
                return process.ExitCode;
            }
            if (string.IsNullOrWhiteSpace(message))
                message = restartRequired
                    ? "Restart Windows to let SwitchTrade Setup continue automatically after sign-in."
                    : success ? "SwitchTrade setup completed." : "SwitchTrade setup did not complete.";
            MessageBox.Show(message, "SwitchTrade Setup", MessageBoxButtons.OK,
                success ? MessageBoxIcon.Information : MessageBoxIcon.Error);
            return process.ExitCode;
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
