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
using SwitchTrade.Desktop.Models;

namespace SwitchTrade.Desktop.Services;

public sealed record BackendLaunchResult(
    bool Succeeded, string Details, string? Code = null, string? Stage = null,
    string? PrimaryAction = null, string? CorrelationId = null);

public interface IHardwareAuthorizationService
{
    Task AuthorizeAsync(HardwareDeviceViewData device, CancellationToken cancellationToken = default);
}

public sealed class WindowsHardwareAuthorizationService : IHardwareAuthorizationService
{
    public async Task AuthorizeAsync(
        HardwareDeviceViewData device, CancellationToken cancellationToken = default)
    {
        var provisioner = Path.Combine(AppContext.BaseDirectory, "SwitchTradeProvisioner.exe");
        if (!File.Exists(provisioner))
            throw Failure("The installed adapter authorization helper is missing.",
                "hardware_authorizer_missing", "Run Setup Repair");
        var start = new ProcessStartInfo
        {
            FileName = provisioner,
            UseShellExecute = true,
            Verb = "runas",
            WindowStyle = ProcessWindowStyle.Hidden,
        };
        foreach (var argument in new[]
        {
            "authorize-hardware", "--instance-id", device.InstanceId,
            "--usb-id", device.UsbId,
        })
            start.ArgumentList.Add(argument);
        try
        {
            using var process = Process.Start(start) ?? throw Failure(
                "Windows could not start adapter authorization.",
                "hardware_authorizer_start_failed", "Try again");
            using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            deadline.CancelAfter(TimeSpan.FromSeconds(60));
            try { await process.WaitForExitAsync(deadline.Token); }
            catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
            {
                throw Failure("Windows adapter authorization took too long.",
                    "hardware_authorizer_timeout", "Reconnect the adapter and try again");
            }
            if (process.ExitCode == 0) return;
            throw process.ExitCode switch
            {
                61 or 68 or 69 => Failure(
                    "The selected adapter changed or was disconnected.",
                    "adapter_identity_changed", "Reconnect and select the adapter again"),
                62 => Failure(
                    "Windows administrator approval is required to authorize this adapter.",
                    "adapter_authorization_required", "Approve the Windows prompt and try again"),
                63 or 64 => Failure(
                    "Windows could not authorize the selected adapter.",
                    "adapter_bind_failed", "Reconnect the adapter and try again"),
                65 or 66 or 67 => Failure(
                    "Windows USB support is unavailable or incompatible.",
                    "usbipd_unavailable", "Run Setup Repair"),
                _ => Failure(
                    "Windows could not authorize the selected adapter.",
                    "adapter_authorization_failed", "Export a support file and try again"),
            };
        }
        catch (Win32Exception error) when (error.NativeErrorCode == 1223)
        {
            throw Failure("Adapter authorization was canceled.",
                "adapter_authorization_canceled", "Approve the Windows prompt and try again");
        }
        catch (Win32Exception error)
        {
            throw Failure($"Windows could not start adapter authorization: {error.Message}",
                "hardware_authorizer_start_failed", "Run Setup Repair");
        }
    }

    private static UserFacingException Failure(string message, string code, string action) =>
        new(message, code, "hardware_share", recoverable: true, primaryAction: action);
}

public sealed class BackendLauncher
{
    private static readonly ConcurrentDictionary<int, Process> RunningProcesses = new();
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private readonly ApplicationSession? _applicationSession;

    public BackendLauncher(ApplicationSession? applicationSession = null) =>
        _applicationSession = applicationSession;

    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The launcher remains an injected service boundary for deterministic UI tests.")]
    public async Task<BackendLaunchResult> StartAsync(CancellationToken cancellationToken)
    {
        _applicationSession?.AppendEvent(
            "launcher", "backend_start_requested", "BACKEND_START_REQUESTED",
            "Starting the installed local service.");
        var result = await StartCoreAsync(cancellationToken);
        if (result.Succeeded)
            _applicationSession?.AppendEvent(
                "launcher", "backend_ready", "BACKEND_READY", "Installed local service is ready.");
        else
            _applicationSession?.RecordStartupFailure(result);
        return result;
    }

    private async Task<BackendLaunchResult> StartCoreAsync(CancellationToken cancellationToken)
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

            var logRoot = _applicationSession?.DirectoryPath ?? Path.Combine(Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData), "SwitchTrade", "logs", "startup");
            Directory.CreateDirectory(logRoot);
            var stamp = DateTime.UtcNow.ToString("yyyyMMddTHHmmssfff",
                System.Globalization.CultureInfo.InvariantCulture);
            var start = new ProcessStartInfo
            {
                FileName = "wsl.exe", UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
            };
            var environment = new List<string>
            {
                $"SWITCHTRADE_RELAY_URL={relayUrl}",
                "SWITCHTRADE_ALLOW_PROCESS_SHUTDOWN=1",
                $"SWITCHTRADE_WSL_DISTRO={status.ActiveRuntime}",
            };
            if (_applicationSession is not null)
            {
                environment.Add($"SWITCHTRADE_APP_SESSION_ID={_applicationSession.Id}");
                environment.Add($"SWITCHTRADE_SESSION_WINDOWS_PATH={_applicationSession.DirectoryPath}");
                environment.Add($"SWITCHTRADE_SESSION_WSL_PATH={_applicationSession.WslDirectoryPath}");
            }
            start.ArgumentList.Add("-d");
            start.ArgumentList.Add(status.ActiveRuntime);
            start.ArgumentList.Add("-u");
            start.ArgumentList.Add("root");
            start.ArgumentList.Add("--cd");
            start.ArgumentList.Add("/opt/switchtrade");
            start.ArgumentList.Add("--");
            start.ArgumentList.Add("env");
            foreach (var variable in environment) start.ArgumentList.Add(variable);
            start.ArgumentList.Add("/opt/switchtrade/bridge/.venv/bin/python");
            start.ArgumentList.Add("-m");
            start.ArgumentList.Add("switchtrade.control");
            var process = Process.Start(start) ?? throw new InvalidOperationException(
                "The local SwitchTrade service process did not start.");
            Track(process, _applicationSession,
                _applicationSession is null ? Path.Combine(logRoot, $"{stamp}-control.out.log") : "control.stdout.log",
                _applicationSession is null ? Path.Combine(logRoot, $"{stamp}-control.err.log") : "control.stderr.log");

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

    public static async Task StopAsync(
        ApplicationSession? applicationSession = null,
        CancellationToken cancellationToken = default)
    {
        applicationSession?.AppendEvent(
            "launcher", "backend_shutdown_requested", "BACKEND_SHUTDOWN_REQUESTED",
            "Stopping the installed local service through its identity-bound command.");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(TimeSpan.FromSeconds(20));
        var graceful = false;
        var forced = false;
        try
        {
            using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(18) };
            var readiness = await ReadinessAsync(deadline.Token);
            using var content = new StringContent("{}", System.Text.Encoding.UTF8, "application/json");
            using var request = new HttpRequestMessage(
                HttpMethod.Post, "http://127.0.0.1:8787/api/v1/app/shutdown") { Content = content };
            request.Headers.Add("X-SwitchTrade-Command-ID", Guid.NewGuid().ToString("D"));
            request.Headers.Add(
                "X-SwitchTrade-Expected-Revision", (readiness?.Revision ?? 0).ToString(
                    System.Globalization.CultureInfo.InvariantCulture));
            if (!string.IsNullOrWhiteSpace(readiness?.RunId))
                request.Headers.Add("X-SwitchTrade-Run-ID", readiness.RunId);
            using var response = await client.SendAsync(request, deadline.Token);
            graceful = response.IsSuccessStatusCode;
        }
        catch (HttpRequestException) { }
        catch (TaskCanceledException) { }

        foreach (var process in RunningProcesses.Values.ToArray())
        {
            try
            {
                if (!process.HasExited)
                    await process.WaitForExitAsync(deadline.Token);
            }
            catch (OperationCanceledException)
            {
                try
                {
                    if (!process.HasExited)
                    {
                        process.Kill(entireProcessTree: true);
                        forced = true;
                    }
                }
                catch (InvalidOperationException) { }
            }
            catch (InvalidOperationException) { }
        }
        applicationSession?.AppendEvent(
            "launcher",
            forced ? "backend_shutdown_forced" :
                graceful ? "backend_shutdown_completed" : "backend_shutdown_unconfirmed",
            forced ? "BACKEND_SHUTDOWN_FORCED" :
                graceful ? "BACKEND_SHUTDOWN_COMPLETED" : "BACKEND_SHUTDOWN_UNCONFIRMED",
            forced
                ? "The local service did not exit inside the cleanup deadline; startup recovery remains required."
                : graceful
                    ? "The local service stopped without a forced process termination."
                    : "The local service shutdown response was unavailable; no tracked process required force.");
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

    private static void Track(
        Process process, ApplicationSession? applicationSession, string outputPath, string errorPath)
    {
        RunningProcesses[process.Id] = process;
        _ = Task.Run(async () =>
        {
            try
            {
                if (applicationSession is not null)
                {
                    await Task.WhenAll(
                        DrainAsync(process.StandardOutput, applicationSession, outputPath),
                        DrainAsync(process.StandardError, applicationSession, errorPath),
                        process.WaitForExitAsync());
                }
                else
                {
                    await using var output = File.Create(outputPath);
                    await using var error = File.Create(errorPath);
                    await Task.WhenAll(process.StandardOutput.BaseStream.CopyToAsync(output),
                        process.StandardError.BaseStream.CopyToAsync(error), process.WaitForExitAsync());
                }
            }
            finally
            {
                RunningProcesses.TryRemove(process.Id, out _);
                process.Dispose();
            }
        });
    }

    private static async Task DrainAsync(
        StreamReader source, ApplicationSession applicationSession, string fileName)
    {
        while (await source.ReadLineAsync() is { } line)
            applicationSession.AppendStreamLine(fileName, line);
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
        [property: JsonPropertyName("compatible")] bool Compatible,
        [property: JsonPropertyName("run_id")] string? RunId,
        [property: JsonPropertyName("revision")] long Revision);
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
