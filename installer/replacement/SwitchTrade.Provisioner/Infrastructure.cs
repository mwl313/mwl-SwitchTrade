using System.Diagnostics;
using System.Diagnostics.CodeAnalysis;
using System.ComponentModel;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;

namespace SwitchTrade.Provisioner;

internal sealed record ProcessResult(int ExitCode, string Output, string Error);

internal static class ProcessRunner
{
    internal static async Task<ProcessResult> RunAsync(
        string fileName, IEnumerable<string> arguments, TimeSpan timeout, CancellationToken cancellationToken = default)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(timeout);
        var start = new ProcessStartInfo
        {
            FileName = fileName,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new InvalidOperationException($"Could not start {fileName}.");
        var stdout = ReadBytesAsync(process.StandardOutput.BaseStream, deadline.Token);
        var stderr = ReadBytesAsync(process.StandardError.BaseStream, deadline.Token);
        try
        {
            await process.WaitForExitAsync(deadline.Token);
            return new ProcessResult(process.ExitCode, Decode(await stdout), Decode(await stderr));
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            try { process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            throw ProvisionerException.Wsl("PROCESS_TIMEOUT", $"{Path.GetFileName(fileName)} exceeded its {timeout.TotalSeconds:0}-second deadline.");
        }
    }

    private static async Task<byte[]> ReadBytesAsync(Stream stream, CancellationToken cancellationToken)
    {
        using var buffer = new MemoryStream();
        await stream.CopyToAsync(buffer, cancellationToken);
        return buffer.ToArray();
    }

    internal static string Decode(byte[] bytes)
    {
        if (bytes.Length == 0) return "";
        var offset = 0;
        Encoding encoding;
        if (bytes.AsSpan().StartsWith(Encoding.Unicode.GetPreamble()))
        {
            encoding = Encoding.Unicode;
            offset = Encoding.Unicode.GetPreamble().Length;
        }
        else if (bytes.AsSpan().StartsWith(Encoding.BigEndianUnicode.GetPreamble()))
        {
            encoding = Encoding.BigEndianUnicode;
            offset = Encoding.BigEndianUnicode.GetPreamble().Length;
        }
        else if (LooksLikeUtf16LittleEndian(bytes))
        {
            encoding = Encoding.Unicode;
        }
        else
        {
            encoding = new UTF8Encoding(false, false);
        }
        return encoding.GetString(bytes, offset, bytes.Length - offset).Trim();
    }

    private static bool LooksLikeUtf16LittleEndian(byte[] bytes)
    {
        var sample = Math.Min(bytes.Length, 256);
        var pairs = sample / 2;
        if (pairs < 2) return false;
        var evenNulls = 0;
        var oddNulls = 0;
        for (var index = 0; index < pairs * 2; index += 2)
        {
            if (bytes[index] == 0) evenNulls++;
            if (bytes[index + 1] == 0) oddNulls++;
        }
        return oddNulls >= 2 && oddNulls * 5 >= pairs && oddNulls > evenNulls * 2;
    }
}

internal sealed class ProvisionerPaths
{
    internal ProvisionerPaths(string? dataRoot = null, string? userProfile = null,
        string? kernelRoot = null)
    {
        DataRoot = Path.GetFullPath(dataRoot ?? Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "SwitchTrade"));
        UserProfile = Path.GetFullPath(userProfile ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
        StateRoot = Path.Combine(DataRoot, "state");
        RuntimeRoot = Path.Combine(DataRoot, "runtimes");
        KernelRoot = Path.GetFullPath(kernelRoot ?? (dataRoot is not null
            ? Path.Combine(DataRoot, "kernel")
            : ProductionKernelRoot(
                Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),
                CurrentUserSid())));
        EnforceAsciiKernelPath = dataRoot is null || kernelRoot is not null;
        LogRoot = Path.Combine(DataRoot, "logs", "setup");
    }

    internal string DataRoot { get; }
    internal string UserProfile { get; }
    internal string StateRoot { get; }
    internal string RuntimeRoot { get; }
    internal string KernelRoot { get; }
    internal bool EnforceAsciiKernelPath { get; }
    internal string LogRoot { get; }
    internal string ActivePath => Path.Combine(StateRoot, "active-runtime.json");
    internal string JournalPath => Path.Combine(StateRoot, "operation.json");
    internal string KernelStatePath => Path.Combine(StateRoot, "kernel-state.v1.json");
    internal string LegacyKernelStatePath => Path.Combine(DataRoot, "kernel-state.json");
    internal string WslConfigPath => Path.Combine(UserProfile, ".wslconfig");

    internal void Ensure() => Directory.CreateDirectory(StateRoot);

    internal static string ProductionKernelRoot(string commonApplicationData, string userSid) =>
        Path.Combine(Path.GetFullPath(commonApplicationData), "SwitchTrade", "users", userSid, "kernel");

    private static string CurrentUserSid()
    {
        using var identity = WindowsIdentity.GetCurrent();
        return identity.User?.Value ?? throw ProvisionerException.State(
            "WINDOWS_IDENTITY_UNAVAILABLE", "The current Windows user SID could not be determined.",
            "Sign out and sign in, then retry Setup");
    }
}

internal static class AtomicFile
{
    internal static T? Read<T>(string path) where T : class
    {
        if (!File.Exists(path)) return null;
        try { return JsonSerializer.Deserialize<T>(File.ReadAllText(path), Contract.Json); }
        catch (JsonException error) { throw ProvisionerException.State("STATE_FILE_INVALID", $"Invalid state file {Path.GetFileName(path)}: {error.Message}"); }
    }

    internal static void Write<T>(string path, T value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + ".tmp." + Guid.NewGuid().ToString("N");
        try
        {
            File.WriteAllText(temporary, JsonSerializer.Serialize(value, Contract.Json) + Environment.NewLine, new UTF8Encoding(false));
            File.Move(temporary, path, true);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }
}

internal sealed record WslRegistration(string Name, string BasePath);

internal interface IWslPlatform
{
    Task<Version> VersionAsync(CancellationToken cancellationToken);
    Task<HashSet<string>> NamesAsync(CancellationToken cancellationToken);
    WslRegistration? Registration(string name);
    Task InstallAsync(string appliance, string name, string location, CancellationToken cancellationToken);
    Task<ProcessResult> RunAsync(string name, IEnumerable<string> arguments, TimeSpan timeout,
        CancellationToken cancellationToken);
    Task TerminateAsync(string name, CancellationToken cancellationToken);
    Task UnregisterAsync(string name, CancellationToken cancellationToken);
    Task ShutdownAsync(CancellationToken cancellationToken);
}

[SuppressMessage("Performance", "CA1822:Mark members as static", Justification = "Instance process boundary is injected into the lifecycle engine and replaced by integration harnesses.")]
internal sealed class WslPlatform : IWslPlatform
{
    private const string Wsl = "wsl.exe";

    public async Task<Version> VersionAsync(CancellationToken cancellationToken)
    {
        ProcessResult result;
        try { result = await ProcessRunner.RunAsync(Wsl, ["--version"], TimeSpan.FromSeconds(20), cancellationToken); }
        catch (Win32Exception)
        {
            throw ProvisionerException.Wsl("WSL_PREREQUISITE_MISSING", "Microsoft Store WSL is not available.");
        }
        if (result.ExitCode != 0)
            throw ProvisionerException.Wsl("WSL_PREREQUISITE_MISSING", "Microsoft Store WSL is not available.");
        var match = System.Text.RegularExpressions.Regex.Match(result.Output + " " + result.Error, @"\d+\.\d+\.\d+(?:\.\d+)?");
        if (!match.Success || !Version.TryParse(match.Value, out var version))
            throw ProvisionerException.Wsl("WSL_VERSION_UNKNOWN", "The installed WSL version could not be determined.");
        return version;
    }

    public async Task<HashSet<string>> NamesAsync(CancellationToken cancellationToken)
    {
        ProcessResult result;
        try { result = await ProcessRunner.RunAsync(Wsl, ["--list", "--quiet"], TimeSpan.FromSeconds(30), cancellationToken); }
        catch (Win32Exception)
        {
            throw ProvisionerException.Wsl("WSL_PREREQUISITE_MISSING", "Microsoft Store WSL is not available.");
        }
        if (result.ExitCode != 0) throw ProvisionerException.Wsl("WSL_ENUMERATION_FAILED", result.Error);
        return result.Output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
    }

    public WslRegistration? Registration(string name)
    {
        using var root = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Lxss");
        if (root is null) return null;
        foreach (var childName in root.GetSubKeyNames())
        {
            using var child = root.OpenSubKey(childName);
            if (!string.Equals(child?.GetValue("DistributionName") as string, name, StringComparison.OrdinalIgnoreCase)) continue;
            var basePath = child?.GetValue("BasePath") as string;
            return string.IsNullOrWhiteSpace(basePath) ? null : new WslRegistration(name, Path.GetFullPath(basePath));
        }
        return null;
    }

    public async Task InstallAsync(string appliance, string name, string location, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(location);
        var result = await ProcessRunner.RunAsync(Wsl,
            ["--install", "--from-file", appliance, "--name", name, "--location", location, "--version", "2", "--no-launch"],
            TimeSpan.FromMinutes(15), cancellationToken);
        if (result.ExitCode != 0) throw ProvisionerException.Wsl("WSL_DISTRO_INSTALL_FAILED", Useful(result));
    }

    public async Task<ProcessResult> RunAsync(string name, IEnumerable<string> arguments, TimeSpan timeout, CancellationToken cancellationToken)
    {
        var all = new List<string> { "-d", name, "-u", "root", "--" };
        all.AddRange(arguments);
        return await ProcessRunner.RunAsync(Wsl, all, timeout, cancellationToken);
    }

    public async Task TerminateAsync(string name, CancellationToken cancellationToken)
    {
        var result = await ProcessRunner.RunAsync(Wsl, ["--terminate", name], TimeSpan.FromSeconds(30), cancellationToken);
        if (result.ExitCode != 0 && !result.Error.Contains("not found", StringComparison.OrdinalIgnoreCase))
            throw ProvisionerException.Wsl("WSL_TERMINATE_FAILED", Useful(result));
    }

    public async Task UnregisterAsync(string name, CancellationToken cancellationToken)
    {
        var result = await ProcessRunner.RunAsync(Wsl, ["--unregister", name], TimeSpan.FromMinutes(2), cancellationToken);
        if (result.ExitCode != 0) throw ProvisionerException.Wsl("WSL_UNREGISTER_FAILED", Useful(result));
    }

    public async Task ShutdownAsync(CancellationToken cancellationToken)
    {
        var result = await ProcessRunner.RunAsync(Wsl, ["--shutdown"], TimeSpan.FromSeconds(30), cancellationToken);
        if (result.ExitCode != 0) throw ProvisionerException.Wsl("WSL_SHUTDOWN_FAILED", Useful(result));
    }

    private static string Useful(ProcessResult result) => string.IsNullOrWhiteSpace(result.Error) ? result.Output : result.Error;
}
