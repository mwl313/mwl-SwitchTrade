using System.ComponentModel;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace SwitchTrade.Desktop.Services;

public sealed record BackendLaunchResult(
    bool Succeeded, string Details, string? Code = null, string? Stage = null,
    string? PrimaryAction = null, string? CorrelationId = null);

public sealed class BackendLauncher
{
    private static readonly ConcurrentDictionary<int, Process> RunningProcesses = new();
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The launcher remains an injected service boundary for deterministic UI tests.")]
    public async Task<BackendLaunchResult> StartAsync(CancellationToken cancellationToken)
    {
        var provisioner = Path.Combine(AppContext.BaseDirectory, "SwitchTradeProvisioner.exe");
        if (!File.Exists(provisioner))
            return Failed("PROVISIONER_MISSING", "desktop_startup",
                "The installed runtime manager is missing.", "Run Setup Repair");
        using var launchMutex = new Mutex(false, "Local\\SwitchTrade.RuntimeLauncher");
        var ownsMutex = false;
        try
        {
            try { ownsMutex = launchMutex.WaitOne(TimeSpan.FromSeconds(15)); }
            catch (AbandonedMutexException) { ownsMutex = true; }
            if (!ownsMutex)
                return Failed("RUNTIME_START_BUSY", "desktop_startup",
                    "Another SwitchTrade startup is still running.", "Wait and try again");

            var statusResult = await RunAsync(provisioner, ["status", "--json"],
                TimeSpan.FromSeconds(30), cancellationToken);
            ProvisionerStatus? status = null;
            try { status = JsonSerializer.Deserialize<ProvisionerStatus>(statusResult.Output, Json); }
            catch (JsonException) { }
            if (statusResult.ExitCode != 0 || status is not { SoftwareReady: true } ||
                string.IsNullOrWhiteSpace(status.ActiveRuntime) ||
                string.IsNullOrWhiteSpace(status.ReleaseId) ||
                status.ControlContract != ControlApiClient.ReadinessContract)
            {
                var error = ParseError(statusResult.Output) ?? ParseError(statusResult.Error);
                return error ?? Failed("SOFTWARE_NOT_READY", "desktop_startup",
                    $"Installed runtime state is {status?.State ?? "unavailable"}.",
                    status?.RecoveryAction ?? "Run Setup Repair");
            }

            var existing = await ReadinessAsync(cancellationToken);
            if (Matches(existing, status)) return new BackendLaunchResult(true, "");
            if (existing is not null)
                return Failed("CONTROL_VERSION_CONFLICT", "desktop_startup",
                    "An incompatible local SwitchTrade service is already using port 8787.",
                    "Close SwitchTrade and try again");

            var relayUrl = ReadRelayUrl(status.ReleaseId);
            if (relayUrl is null)
                return Failed("RELEASE_STATE_INVALID", "desktop_startup",
                    "The installed release configuration is missing or incompatible.", "Run Setup Repair");

            var logRoot = Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData), "SwitchTrade", "logs", "startup");
            Directory.CreateDirectory(logRoot);
            var stamp = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfff",
                System.Globalization.CultureInfo.InvariantCulture);
            var start = new ProcessStartInfo
            {
                FileName = "wsl.exe", UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
            };
            foreach (var argument in new[]
            {
                "-d", status.ActiveRuntime, "-u", "root", "--cd", "/opt/switchtrade", "--",
                "env", $"SWITCHTRADE_RELAY_URL={relayUrl}",
                "SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN=1", $"SWITCHTRADE_WSL_DISTRO={status.ActiveRuntime}",
                "/opt/switchtrade/bridge/.venv/bin/python", "-m", "switchtrade.control",
            })
                start.ArgumentList.Add(argument);
            var process = Process.Start(start) ?? throw new InvalidOperationException(
                "The local SwitchTrade service process did not start.");
            Track(process, Path.Combine(logRoot, $"{stamp}-control.out.log"),
                Path.Combine(logRoot, $"{stamp}-control.err.log"));

            for (var attempt = 0; attempt < 40; attempt++)
            {
                cancellationToken.ThrowIfCancellationRequested();
                var readiness = await ReadinessAsync(cancellationToken);
                if (Matches(readiness, status)) return new BackendLaunchResult(true, "");
                if (process.HasExited) break;
                await Task.Delay(500, cancellationToken);
            }
            if (!process.HasExited) process.Kill(entireProcessTree: true);
            return Failed("CONTROL_START_FAILED", "desktop_startup",
                "The installed local service did not reach its readiness contract. See startup logs.",
                "Run Setup Repair");
        }
        catch (InvalidOperationException error) { return new BackendLaunchResult(false, error.Message); }
        catch (Win32Exception error) { return new BackendLaunchResult(false, error.Message); }
        catch (IOException error) { return new BackendLaunchResult(false, error.Message); }
        catch (JsonException error) { return new BackendLaunchResult(false, error.Message); }
        finally { if (ownsMutex) launchMutex.ReleaseMutex(); }
    }

    private static async Task<ProcessResult> RunAsync(
        string fileName, IEnumerable<string> arguments, TimeSpan timeout, CancellationToken cancellationToken)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(timeout);
        var start = new ProcessStartInfo
        {
            FileName = fileName, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
        };
        foreach (var argument in arguments) start.ArgumentList.Add(argument);
        using var process = Process.Start(start) ?? throw new InvalidOperationException(
            $"Could not start {Path.GetFileName(fileName)}.");
        var output = process.StandardOutput.ReadToEndAsync(deadline.Token);
        var error = process.StandardError.ReadToEndAsync(deadline.Token);
        try { await process.WaitForExitAsync(deadline.Token); }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            try { process.Kill(entireProcessTree: true); } catch (InvalidOperationException) { }
            return new ProcessResult(1460, "", "The runtime manager timed out.");
        }
        return new ProcessResult(process.ExitCode, await output, await error);
    }

    private static async Task<Readiness?> ReadinessAsync(CancellationToken cancellationToken)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
        try
        {
            using var response = await client.GetAsync(
                "http://127.0.0.1:8787/api/v1/app/readiness", cancellationToken);
            if (!response.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<Readiness>(await response.Content.ReadAsStringAsync(cancellationToken), Json);
        }
        catch (HttpRequestException) { return null; }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested) { return null; }
        catch (JsonException) { return null; }
    }

    private static bool Matches(Readiness? readiness, ProvisionerStatus status) =>
        readiness is { Compatible: true } && readiness.ContractVersion == status.ControlContract &&
        readiness.ReleaseId == status.ReleaseId;

    private static string? ReadRelayUrl(string releaseId)
    {
        var path = Path.Combine(AppContext.BaseDirectory, "release-manifest.json");
        using var document = JsonDocument.Parse(File.ReadAllBytes(path));
        var root = document.RootElement;
        if (root.GetProperty("release_id").GetString() != releaseId) return null;
        var value = root.GetProperty("relay_url").GetString();
        return Uri.TryCreate(value, UriKind.Absolute, out var relay) && relay.Scheme == Uri.UriSchemeHttps
            ? relay.AbsoluteUri : null;
    }

    private static BackendLaunchResult? ParseError(string value)
    {
        try
        {
            var error = JsonSerializer.Deserialize<ProvisionerError>(value, Json);
            return error?.Code is null ? null : Failed(error.Code, error.Stage ?? "desktop_startup",
                error.Message ?? "The runtime manager failed.", error.PrimaryAction ?? "Run Setup Repair",
                error.CorrelationId?.ToString());
        }
        catch (JsonException) { return null; }
    }

    private static BackendLaunchResult Failed(string code, string stage, string message,
        string action, string? correlationId = null) =>
        new(false, message, code, stage, action, correlationId);

    private static void Track(Process process, string outputPath, string errorPath)
    {
        RunningProcesses[process.Id] = process;
        var output = File.Create(outputPath);
        var error = File.Create(errorPath);
        _ = Task.Run(async () =>
        {
            try
            {
                await Task.WhenAll(process.StandardOutput.BaseStream.CopyToAsync(output),
                    process.StandardError.BaseStream.CopyToAsync(error), process.WaitForExitAsync());
            }
            finally
            {
                output.Dispose(); error.Dispose();
                RunningProcesses.TryRemove(process.Id, out _);
                process.Dispose();
            }
        });
    }

    private sealed record ProcessResult(int ExitCode, string Output, string Error);
    private sealed record ProvisionerStatus(
        [property: JsonPropertyName("state")] string? State,
        [property: JsonPropertyName("software_ready")] bool SoftwareReady,
        [property: JsonPropertyName("release_id")] string? ReleaseId,
        [property: JsonPropertyName("active_runtime")] string? ActiveRuntime,
        [property: JsonPropertyName("control_contract")] string? ControlContract,
        [property: JsonPropertyName("recovery_action")] string? RecoveryAction);
    private sealed record ProvisionerError(
        [property: JsonPropertyName("code")] string? Code,
        [property: JsonPropertyName("stage")] string? Stage,
        [property: JsonPropertyName("message")] string? Message,
        [property: JsonPropertyName("primary_action")] string? PrimaryAction,
        [property: JsonPropertyName("correlation_id")] Guid? CorrelationId);
    private sealed record Readiness(
        [property: JsonPropertyName("contract_version")] string? ContractVersion,
        [property: JsonPropertyName("release_id")] string? ReleaseId,
        [property: JsonPropertyName("compatible")] bool Compatible);
}

public enum DialogChoice { Primary, Secondary, Cancel }

public sealed record DialogRequest(
    string Title,
    string Message,
    string PrimaryLabel,
    string CancelLabel = "Cancel",
    string? SecondaryLabel = null,
    bool IsDestructive = false);

public interface IDialogService
{
    DialogChoice Show(DialogRequest request);
}

public sealed class WindowsDialogService : IDialogService
{
    public DialogChoice Show(DialogRequest request)
    {
        var previousFocus = Keyboard.FocusedElement;
        var result = DialogChoice.Cancel;
        var window = new Window
        {
            Title = request.Title,
            Owner = Application.Current?.MainWindow,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            SizeToContent = SizeToContent.Height,
            Width = 480,
            MinHeight = 220,
            MaxHeight = 620,
            ResizeMode = ResizeMode.NoResize,
            ShowInTaskbar = false,
            Background = Application.Current?.TryFindResource("SurfaceBrush") as Brush ?? Brushes.White,
            FontFamily = Application.Current?.TryFindResource("BodyFontFamily") as FontFamily ??
                         throw new InvalidOperationException("SwitchTrade body font resource is missing."),
            FontSize = 15,
        };

        var primary = Button(request.PrimaryLabel, request.IsDestructive ? "DangerButton" : "PrimaryButton");
        primary.IsDefault = !request.IsDestructive;
        primary.Click += (_, _) => { result = DialogChoice.Primary; window.DialogResult = true; };

        var cancel = Button(request.CancelLabel, "SecondaryButton");
        cancel.IsCancel = true;
        cancel.Click += (_, _) => { result = DialogChoice.Cancel; window.DialogResult = false; };

        var actions = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right };
        if (!string.IsNullOrWhiteSpace(request.SecondaryLabel))
        {
            var secondary = Button(request.SecondaryLabel!, "TextButton");
            secondary.Margin = new Thickness(0, 0, 8, 0);
            secondary.Click += (_, _) => { result = DialogChoice.Secondary; window.DialogResult = true; };
            actions.Children.Add(secondary);
        }
        cancel.Margin = new Thickness(0, 0, 8, 0);
        actions.Children.Add(cancel);
        actions.Children.Add(primary);

        var content = new StackPanel { Margin = new Thickness(28) };
        var title = new TextBlock
        {
            Text = request.Title,
            FontFamily = Application.Current?.TryFindResource("HeadingFontFamily") as FontFamily ??
                         throw new InvalidOperationException("SwitchTrade heading font resource is missing."),
            FontSize = 22,
            FontWeight = FontWeights.SemiBold,
            TextWrapping = TextWrapping.Wrap,
            Margin = new Thickness(0, 0, 0, 12),
        };
        AutomationProperties.SetHeadingLevel(title, AutomationHeadingLevel.Level1);
        content.Children.Add(title);
        content.Children.Add(new TextBlock
        {
            Text = request.Message,
            TextWrapping = TextWrapping.Wrap,
            LineHeight = 22,
            Margin = new Thickness(0, 0, 0, 28),
        });
        content.Children.Add(actions);
        window.Content = content;
        window.ShowDialog();
        if (previousFocus is UIElement element) element.Dispatcher.BeginInvoke(element.Focus);
        return result;
    }

    private static Button Button(string label, string styleKey)
    {
        var button = new Button { Content = label, MinWidth = 96 };
        button.SetResourceReference(FrameworkElement.StyleProperty, styleKey);
        AutomationProperties.SetName(button, label);
        return button;
    }
}

public interface IClipboardService
{
    bool TrySetText(string text);
    bool TryGetText(out string text);
}

public sealed class WindowsClipboardService : IClipboardService
{
    public bool TrySetText(string text)
    {
        if (string.IsNullOrWhiteSpace(text)) return false;
        try
        {
            Clipboard.SetText(text);
            return true;
        }
        catch (ExternalException) { return false; }
        catch (ThreadStateException) { return false; }
    }

    public bool TryGetText(out string text)
    {
        text = "";
        try
        {
            if (!Clipboard.ContainsText()) return false;
            text = Clipboard.GetText();
            return !string.IsNullOrWhiteSpace(text);
        }
        catch (ExternalException) { return false; }
        catch (ThreadStateException) { return false; }
    }
}

public sealed class MotionPreferences : IDisposable
{
    public event EventHandler? Changed;
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "This value belongs to the instance that publishes system-setting changes.")]
    public bool IsEnabled => SystemParameters.ClientAreaAnimation && !SystemParameters.HighContrast;

    public MotionPreferences() => SystemParameters.StaticPropertyChanged += SystemSettingChanged;

    private void SystemSettingChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName is nameof(SystemParameters.ClientAreaAnimation) or nameof(SystemParameters.HighContrast))
            Changed?.Invoke(this, EventArgs.Empty);
    }

    public void Dispose() => SystemParameters.StaticPropertyChanged -= SystemSettingChanged;
}
