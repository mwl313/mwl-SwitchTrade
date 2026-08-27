using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SwitchTrade.Provisioner;

internal sealed record TextDocument(string Text, Encoding Encoding, bool Bom, string NewLine, bool FinalNewLine)
{
    internal static TextDocument Read(string path)
    {
        var bytes = File.ReadAllBytes(path);
        Encoding encoding;
        var offset = 0;
        var bom = false;
        if (bytes.AsSpan().StartsWith(Encoding.UTF8.GetPreamble()))
        {
            encoding = new UTF8Encoding(true, true); offset = 3; bom = true;
        }
        else if (bytes.AsSpan().StartsWith(Encoding.Unicode.GetPreamble()))
        {
            encoding = new UnicodeEncoding(false, true, true); offset = 2; bom = true;
        }
        else if (bytes.AsSpan().StartsWith(Encoding.BigEndianUnicode.GetPreamble()))
        {
            encoding = new UnicodeEncoding(true, true, true); offset = 2; bom = true;
        }
        else encoding = new UTF8Encoding(false, true);
        string text;
        try { text = encoding.GetString(bytes, offset, bytes.Length - offset); }
        catch (DecoderFallbackException error)
        {
            throw ProvisionerException.Kernel("WSLCONFIG_ENCODING_UNSUPPORTED", $".wslconfig is not UTF-8 or BOM-marked UTF-16: {error.Message}", false);
        }
        var newline = text.Contains("\r\n", StringComparison.Ordinal) ? "\r\n" : "\n";
        return new TextDocument(text, encoding, bom, newline,
            text.EndsWith('\n'));
    }

    internal static TextDocument Empty => new("", new UTF8Encoding(false, true), false, "\r\n", true);

    internal byte[] Bytes(string value)
    {
        var body = Encoding.GetBytes(value);
        if (!Bom) return body;
        var preamble = Encoding.GetPreamble();
        var result = new byte[preamble.Length + body.Length];
        preamble.CopyTo(result, 0);
        body.CopyTo(result, preamble.Length);
        return result;
    }
}

internal static partial class WslConfig
{
    [GeneratedRegex("^\\s*\\[([^]]+)]\\s*$", RegexOptions.CultureInvariant)]
    private static partial Regex SectionPattern();
    [GeneratedRegex("^\\s*([^#;=\\s]+)\\s*=\\s*(.*?)\\s*$", RegexOptions.CultureInvariant)]
    private static partial Regex ValuePattern();

    internal static Dictionary<string, string> Values(string text)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var section = "";
        foreach (var line in Regex.Split(text, "\\r?\\n"))
        {
            var sectionMatch = SectionPattern().Match(line);
            if (sectionMatch.Success) { section = sectionMatch.Groups[1].Value; continue; }
            var valueMatch = ValuePattern().Match(line);
            if (section.Equals("wsl2", StringComparison.OrdinalIgnoreCase) && valueMatch.Success)
                result.TryAdd(valueMatch.Groups[1].Value, valueMatch.Groups[2].Value);
        }
        return result;
    }

    internal static string Merge(TextDocument document, IReadOnlyDictionary<string, string?> values)
    {
        var lines = Regex.Split(document.Text, "\\r?\\n").ToList();
        if (lines.Count > 0 && lines[^1].Length == 0) lines.RemoveAt(lines.Count - 1);
        var result = new List<string>();
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var inWsl2 = false;
        var foundWsl2 = false;

        void AppendMissing()
        {
            if (!inWsl2) return;
            foreach (var (key, value) in values)
                if (value is not null && seen.Add(key)) result.Add($"{key}={value}");
            inWsl2 = false;
        }

        foreach (var line in lines)
        {
            var section = SectionPattern().Match(line);
            if (section.Success)
            {
                AppendMissing();
                inWsl2 = section.Groups[1].Value.Equals("wsl2", StringComparison.OrdinalIgnoreCase);
                foundWsl2 |= inWsl2;
                result.Add(line);
                continue;
            }
            var setting = ValuePattern().Match(line);
            if (inWsl2 && setting.Success && values.TryGetValue(setting.Groups[1].Value, out var replacement))
            {
                if (seen.Add(setting.Groups[1].Value) && replacement is not null)
                    result.Add($"{setting.Groups[1].Value}={replacement}");
                continue;
            }
            result.Add(line);
        }
        AppendMissing();
        if (!foundWsl2)
        {
            if (result.Count > 0 && result[^1].Length > 0) result.Add("");
            result.Add("[wsl2]");
            foreach (var (key, value) in values)
                if (value is not null) result.Add($"{key}={value}");
        }
        var merged = string.Join(document.NewLine, result);
        return document.FinalNewLine || string.IsNullOrEmpty(document.Text) ? merged + document.NewLine : merged;
    }
}

internal sealed class KernelManager(ProvisionerPaths paths)
{
    internal KernelState Apply(ReleaseManifest manifest, string packageRoot)
    {
        var source = manifest.PayloadPath(packageRoot, "kernel");
        Directory.CreateDirectory(paths.KernelRoot);
        Directory.CreateDirectory(Path.Combine(paths.StateRoot, "backups"));
        var identity = Contract.HashFile(source)[..12];
        var safeRelease = Regex.Replace(manifest.Kernel.Release, "[^A-Za-z0-9._-]", "_");
        var installed = Path.Combine(paths.KernelRoot, $"kernel-{safeRelease}-{identity}");
        if (!File.Exists(installed)) File.Copy(source, installed);
        if (Contract.HashFile(installed) != Contract.HashFile(source))
            throw ProvisionerException.Kernel("KERNEL_COPY_HASH_MISMATCH", "The installed custom kernel does not match the package.");

        var existing = AtomicFile.Read<KernelState>(paths.KernelStatePath);
        string backup;
        bool originalExists;
        string originalHash;
        if (existing is null)
        {
            backup = Path.Combine(paths.StateRoot, "backups", "wslconfig-original.bin");
            var legacy = ReadLegacyBackup();
            originalExists = legacy?.Exists ?? File.Exists(paths.WslConfigPath);
            File.WriteAllBytes(backup, legacy?.Bytes ?? (originalExists ? File.ReadAllBytes(paths.WslConfigPath) : []));
            originalHash = Contract.HashFile(backup);
        }
        else
        {
            backup = existing.OriginalBackup;
            originalExists = existing.OriginalExists;
            originalHash = existing.OriginalSha256;
            if (!File.Exists(backup) || Contract.HashFile(backup) != originalHash)
                throw ProvisionerException.Kernel("KERNEL_BACKUP_INVALID", "The pre-SwitchTrade .wslconfig backup is missing or corrupt.", false);
        }

        var document = File.Exists(paths.WslConfigPath) ? TextDocument.Read(paths.WslConfigPath) : TextDocument.Empty;
        var appliedValue = installed.Replace("\\", "\\\\", StringComparison.Ordinal);
        var merged = WslConfig.Merge(document, new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            ["kernel"] = appliedValue,
            ["kernelModules"] = null,
        });
        WriteAtomicBytes(paths.WslConfigPath, document.Bytes(merged));
        var state = new KernelState(1, originalExists, backup, originalHash, installed,
            Contract.HashFile(installed), manifest.Kernel.Release, appliedValue);
        AtomicFile.Write(paths.KernelStatePath, state);
        return state;
    }

    internal void Restore()
    {
        var state = AtomicFile.Read<KernelState>(paths.KernelStatePath);
        if (state is null) return;
        if (!File.Exists(state.OriginalBackup) || Contract.HashFile(state.OriginalBackup) != state.OriginalSha256)
            throw ProvisionerException.Kernel("KERNEL_BACKUP_INVALID", "The pre-SwitchTrade .wslconfig backup is missing or corrupt.", false);

        var current = File.Exists(paths.WslConfigPath) ? TextDocument.Read(paths.WslConfigPath) : TextDocument.Empty;
        var currentValues = WslConfig.Values(current.Text);
        if (!currentValues.TryGetValue("kernel", out var kernel) || kernel != state.AppliedKernelValue)
        {
            var conflict = Path.Combine(paths.StateRoot, $"wslconfig-user-change-{DateTime.UtcNow:yyyyMMddTHHmmssfff}.bak");
            if (File.Exists(paths.WslConfigPath)) File.Copy(paths.WslConfigPath, conflict);
            throw ProvisionerException.Kernel("WSLCONFIG_OWNERSHIP_CHANGED",
                "The active WSL kernel setting was changed after SwitchTrade installation; the current file was preserved.", false);
        }

        if (!state.OriginalExists && Contract.HashFile(paths.WslConfigPath) == HashBytes(current.Bytes(
                WslConfig.Merge(TextDocument.Empty, new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
                { ["kernel"] = state.AppliedKernelValue, ["kernelModules"] = null }))))
        {
            File.Delete(paths.WslConfigPath);
            return;
        }

        var original = state.OriginalExists ? TextDocument.Read(state.OriginalBackup) : TextDocument.Empty;
        var originalValues = WslConfig.Values(original.Text);
        var merged = WslConfig.Merge(current, new Dictionary<string, string?>(StringComparer.OrdinalIgnoreCase)
        {
            ["kernel"] = originalValues.GetValueOrDefault("kernel"),
            ["kernelModules"] = originalValues.GetValueOrDefault("kernelModules"),
        });
        WriteAtomicBytes(paths.WslConfigPath, current.Bytes(merged));
    }

    private static string HashBytes(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();

    private (bool Exists, byte[] Bytes)? ReadLegacyBackup()
    {
        if (!File.Exists(paths.LegacyKernelStatePath)) return null;
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllText(paths.LegacyKernelStatePath));
            var root = document.RootElement;
            if (!root.TryGetProperty("prior_config_present", out var present) ||
                !root.TryGetProperty("prior_config_backup", out var backup)) return null;
            var backupPath = backup.GetString();
            if (string.IsNullOrWhiteSpace(backupPath) || !File.Exists(backupPath)) return null;
            return (present.GetBoolean(), File.ReadAllBytes(backupPath));
        }
        catch (JsonException) { return null; }
    }

    private static void WriteAtomicBytes(string path, byte[] bytes)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp." + Guid.NewGuid().ToString("N");
        try { File.WriteAllBytes(temporary, bytes); File.Move(temporary, path, true); }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}
