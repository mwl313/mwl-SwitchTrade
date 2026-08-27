using System.Diagnostics;
using System.Text.Json;

namespace SwitchTrade.Provisioner;

internal interface IRuntimeHealth
{
    Task CheckAsync(string name, string releaseId, string contract, CancellationToken cancellationToken);
}

internal sealed class WslRuntimeHealth(IWslPlatform wsl) : IRuntimeHealth
{
    public async Task CheckAsync(string name, string releaseId, string contract,
        CancellationToken cancellationToken)
    {
        const int port = 18787;
        var start = new ProcessStartInfo
        {
            FileName = "wsl.exe", UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var argument in new[]
        {
            "-d", name, "-u", "root", "--cd", "/opt/switchtrade", "--",
            "timeout", "25s", "env", $"SWITCHTRADE_CONTROL_PORT={port}",
            "SWITCHTRADE_RELAY_URL=http://127.0.0.1:9", "SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN=1",
            "/opt/switchtrade/bridge/.venv/bin/python", "-m", "switchtrade.control",
        }) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw ProvisionerException.Wsl(
            "CONTROL_HEALTH_START_FAILED", "The local health process did not start.");
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            for (var attempt = 0; attempt < 40; attempt++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                if (process.HasExited) break;
                try
                {
                    using var response = await client.GetAsync(
                        $"http://127.0.0.1:{port}/api/v1/app/readiness", cancellationToken);
                    if (response.IsSuccessStatusCode)
                    {
                        using var body = await JsonDocument.ParseAsync(
                            await response.Content.ReadAsStreamAsync(cancellationToken),
                            cancellationToken: cancellationToken);
                        var root = body.RootElement;
                        if (root.GetProperty("contract_version").GetString() == contract &&
                            root.GetProperty("release_id").GetString() == releaseId) return;
                    }
                }
                catch (HttpRequestException) { }
                catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested) { }
                await Task.Delay(500, cancellationToken);
            }
            var error = process.HasExited
                ? await process.StandardError.ReadToEndAsync(cancellationToken)
                : "The readiness deadline expired.";
            throw ProvisionerException.Wsl("CONTROL_HEALTH_FAILED", error);
        }
        finally
        {
            try { if (!process.HasExited) process.Kill(entireProcessTree: true); }
            catch (InvalidOperationException) { }
            try { await wsl.TerminateAsync(name, CancellationToken.None); }
            catch (ProvisionerException) { }
        }
    }
}
