using System.Diagnostics;
using System.Globalization;

namespace SwitchTrade.Prerequisites;

internal static class Program
{
    private static readonly string[] Features =
    [
        "Microsoft-Windows-Subsystem-Linux",
        "VirtualMachinePlatform",
    ];

    private static async Task<int> Main(string[] args)
    {
        var action = args.FirstOrDefault()?.ToLowerInvariant() ?? "install";
        if (action == "--self-test")
            return IsEnabled("State : Enabled") && !IsEnabled("State : Disabled") ? 0 : 1;
        if (action is not ("install" or "verify")) return Fail(
            "PREREQUISITE_USAGE", "Expected install or verify.", 2);
        if (!OperatingSystem.IsWindowsVersionAtLeast(10, 0, 19045) ||
            !Environment.Is64BitOperatingSystem)
            return Fail("WINDOWS_VERSION_UNSUPPORTED",
                "SwitchTrade requires Windows 10 22H2 build 19045 or newer on x64.", 10);

        var reboot = false;
        foreach (var feature in Features)
        {
            var state = await DismAsync("/Online", "/Get-FeatureInfo", $"/FeatureName:{feature}");
            if (state.ExitCode == 0 && IsEnabled(state.Output)) continue;
            if (action == "verify") return Fail("WINDOWS_FEATURE_DISABLED",
                $"Required Windows feature is disabled: {feature}", 20);
            var enabled = await DismAsync("/Online", "/Enable-Feature",
                $"/FeatureName:{feature}", "/All", "/NoRestart");
            if (enabled.ExitCode is not (0 or 3010))
                return Fail("WINDOWS_FEATURE_ENABLE_FAILED",
                    $"Could not enable {feature}. DISM exit code: {enabled.ExitCode}", 21);
            reboot |= enabled.ExitCode == 3010 ||
                      enabled.Output.Contains("restart needed", StringComparison.OrdinalIgnoreCase);
        }
        return reboot ? 3010 : 0;
    }

    private static bool IsEnabled(string output) =>
        output.Split(['\r', '\n'], StringSplitOptions.RemoveEmptyEntries)
            .Any(line => line.Trim().Equals("State : Enabled", StringComparison.OrdinalIgnoreCase));

    private static async Task<Result> DismAsync(params string[] arguments)
    {
        var system = Environment.GetFolderPath(Environment.SpecialFolder.System);
        var start = new ProcessStartInfo
        {
            FileName = Path.Combine(system, "dism.exe"),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("/English");
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new InvalidOperationException("DISM did not start.");
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        var output = process.StandardOutput.ReadToEndAsync(deadline.Token);
        var error = process.StandardError.ReadToEndAsync(deadline.Token);
        try { await process.WaitForExitAsync(deadline.Token); }
        catch (OperationCanceledException)
        {
            try { process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            return new Result(1460, "DISM timed out.");
        }
        return new Result(process.ExitCode, string.Join(Environment.NewLine,
            await output, await error));
    }

    private static int Fail(string code, string message, int exitCode)
    {
        Console.Error.WriteLine(string.Create(CultureInfo.InvariantCulture,
            $"[{code}] {message}"));
        return exitCode;
    }

    private sealed record Result(int ExitCode, string Output);
}
