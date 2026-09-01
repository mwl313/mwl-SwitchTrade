using System.IO.Compression;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace SwitchTrade.Desktop.Services;

public sealed class ApplicationSession
{
    private const long SessionLimit = 64L * 1024 * 1024;
    private const long TerminalReserve = 2L * 1024 * 1024;
    private const long StreamLimit = 8L * 1024 * 1024;
    private const int LineLimit = 16 * 1024;
    private const int SessionCountLimit = 10;
    private const long RetentionLimit = 256L * 1024 * 1024;
    private static readonly UTF8Encoding Utf8 = new(false);
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true };
    private static readonly Regex Secret = new(
        "(?i)(member[_-]?token|reconnect[_-]?token|room[_-]?code|instance[_-]?id|trainer|pokemon|passcode|credential|authorization|secret|private[_-]?key)(\\s*[=:]\\s*|\\\"\\s*:\\s*\\\")[^\\s,;\\\"}]+",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly Regex Mac = new(
        "(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private readonly object _gate = new();
    private readonly string _root;
    private readonly string _profile;
    private string? _previousAbnormalSession;
    private bool _completed;

    private ApplicationSession(string root, string id, string directoryPath, string profile)
    {
        _root = root;
        _profile = profile;
        Id = id;
        DirectoryPath = directoryPath;
        WslDirectoryPath = ToWslPath(directoryPath);
    }

    public string Id { get; }
    public string DirectoryPath { get; }
    public string WslDirectoryPath { get; }

    public static ApplicationSession Create(string? root = null)
    {
        root ??= Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "SwitchTrade", "support-sessions");
        Directory.CreateDirectory(root);
        var id = Guid.NewGuid().ToString("D");
        var stamp = DateTime.UtcNow.ToString(
            "yyyyMMddTHHmmssfffZ", System.Globalization.CultureInfo.InvariantCulture);
        var directory = Path.Combine(root, $"{stamp}-{id[..8]}");
        Directory.CreateDirectory(directory);
        var session = new ApplicationSession(
            root, id, directory,
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile));
        session._previousAbnormalSession = session.FindPreviousAbnormalSession();
        session.WriteManifest("running", null);
        session.AppendEvent("launcher", "application_session_started", "APP_SESSION_STARTED",
            "Application evidence session started.");
        session.ApplyRetention();
        return session;
    }

    public void AppendEvent(string component, string eventName, string code, string message)
    {
        var payload = JsonSerializer.Serialize(new Dictionary<string, object>
        {
            ["schema"] = "application-event.v1",
            ["app_session_id"] = Id,
            ["utc"] = DateTimeOffset.UtcNow.ToString("O"),
            ["process_monotonic_ms"] = Environment.TickCount64,
            ["pid"] = Environment.ProcessId,
            ["component"] = component,
            ["event"] = eventName,
            ["code"] = code,
            ["message"] = Redact(message),
        });
        AppendLine("launcher-events.jsonl", payload, terminalEvidence: true);
    }

    public void AppendStreamLine(string fileName, string? line)
    {
        if (line is null || !IsOwnedStreamName(fileName)) return;
        AppendLine(fileName, Redact(line), terminalEvidence: false, StreamLimit);
    }

    public void RecordStartupFailure(BackendLaunchResult failure)
    {
        var summary = new Dictionary<string, object?>
        {
            ["schema"] = "failure-summary.v1",
            ["app_session_id"] = Id,
            ["run_id"] = "not-created",
            ["attempt_id"] = "not-created",
            ["release_id"] = ReadReleaseId(),
            ["last_passed_gate"] = "none",
            ["primary_failure"] = new Dictionary<string, object?>
            {
                ["component"] = "launcher",
                ["stage"] = failure.Stage ?? "desktop_startup",
                ["gate"] = "APP_STARTUP",
                ["code"] = failure.Code ?? "CONTROL_START_FAILED",
                ["message"] = Redact(failure.Details),
            },
            ["functional_outcome"] = "failed",
            ["cleanup"] = new Dictionary<string, object> { ["status"] = "not_started" },
            ["startup_recovery"] = new Dictionary<string, object> { ["required"] = false },
            ["evidence"] = new[] { "application-session.v1.json", "launcher-events.jsonl" },
        };
        WriteJson("failure-summary.v1.json", summary);
        AppendEvent("launcher", "startup_failed", failure.Code ?? "CONTROL_START_FAILED", failure.Details);
    }

    public void Complete(string exitStatus = "clean")
    {
        lock (_gate)
        {
            if (_completed) return;
            _completed = true;
            AppendEvent("launcher", "application_session_stopped", "APP_SESSION_STOPPED",
                "Application evidence session stopped.");
            WriteManifest(exitStatus, DateTimeOffset.UtcNow);
        }
    }

    public async Task<string> ExportAsync(
        string? destinationDirectory = null, CancellationToken cancellationToken = default)
    {
        destinationDirectory ??= Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory);
        if (string.IsNullOrWhiteSpace(destinationDirectory))
            throw new IOException("The Windows Desktop folder is unavailable.");
        Directory.CreateDirectory(destinationDirectory);
        AppendEvent("launcher", "support_export_started", "SUPPORT_EXPORT_STARTED",
            "Creating local support archive.");

        var stamp = DateTime.UtcNow.ToString(
            "yyyyMMddTHHmmssZ", System.Globalization.CultureInfo.InvariantCulture);
        var finalPath = Path.Combine(destinationDirectory,
            $"SwitchTrade-support-{stamp}-{Id[..8]}.zip");
        var partialPath = finalPath + ".partial";
        var entries = new List<Dictionary<string, object>>();
        try
        {
            await using (var stream = new FileStream(
                             partialPath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None,
                             64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan))
            using (var archive = new ZipArchive(stream, ZipArchiveMode.Create, leaveOpen: false))
            {
                long remaining = SessionLimit;
                foreach (var sessionDirectory in ExportSessionDirectories())
                {
                    var prefix = Path.GetFileName(sessionDirectory);
                    foreach (var file in EnumerateAllowedFiles(sessionDirectory))
                    {
                        cancellationToken.ThrowIfCancellationRequested();
                        if (remaining <= 0) break;
                        var originalSize = new FileInfo(file).Length;
                        var content = await ReadBoundedRedactedAsync(
                            file, Math.Min(StreamLimit, remaining), cancellationToken);
                        remaining -= content.LongLength;
                        var name = $"sessions/{prefix}/{Path.GetRelativePath(sessionDirectory, file).Replace('\\', '/')}";
                        var entry = archive.CreateEntry(name, CompressionLevel.Optimal);
                        await using (var destination = entry.Open())
                            await destination.WriteAsync(content, cancellationToken);
                        entries.Add(new Dictionary<string, object>
                        {
                            ["path"] = name,
                            ["sha256"] = Convert.ToHexString(SHA256.HashData(content)).ToLowerInvariant(),
                            ["original_size"] = originalSize,
                            ["included_size"] = content.LongLength,
                            ["truncated"] = content.LongLength < originalSize,
                            ["redacted"] = true,
                        });
                    }
                }
                var manifestEntry = archive.CreateEntry("support-export.v1.json", CompressionLevel.Optimal);
                await using var manifestStream = manifestEntry.Open();
                await JsonSerializer.SerializeAsync(manifestStream, new Dictionary<string, object>
                {
                    ["schema"] = "support-export.v1",
                    ["app_session_id"] = Id,
                    ["created_utc"] = DateTimeOffset.UtcNow.ToString("O"),
                    ["files"] = entries,
                }, Json, cancellationToken);
            }
            File.Move(partialPath, finalPath, overwrite: false);
            AppendEvent("launcher", "support_export_completed", "SUPPORT_EXPORT_COMPLETED",
                $"Support archive created as {Path.GetFileName(finalPath)}.");
            return finalPath;
        }
        catch
        {
            try { File.Delete(partialPath); }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            throw;
        }
    }

    internal static string ToWslPath(string windowsPath)
    {
        var full = Path.GetFullPath(windowsPath);
        if (full.Length < 3 || full[1] != ':' || full[2] != Path.DirectorySeparatorChar)
            throw new ArgumentException("A local drive path is required.", nameof(windowsPath));
        var tail = full[3..].Replace('\\', '/');
        return $"/mnt/{char.ToLowerInvariant(full[0])}/{tail}";
    }

    internal static bool SelfTest()
    {
        var temporaryRoot = Path.Combine(
            Path.GetTempPath(), $"SwitchTrade-session-selftest-{Guid.NewGuid():N}");
        try
        {
            var session = Create(temporaryRoot);
            session.AppendStreamLine(
                "control.stderr.log", "사용자 member_token=private-value room_code=ABC123 " +
                "instance_id=USB\\VID_0BDA&PID_818B\\RADIO-A 00:11:22:33:44:55");
            var runDirectory = Path.Combine(session.DirectoryPath, "connection-runs", "self-test");
            Directory.CreateDirectory(runDirectory);
            File.WriteAllText(
                Path.Combine(runDirectory, "worker-events.ndjson"),
                "{\"event\":\"endpoint_started\",\"member_token\":\"nested-private\"}\n", Utf8);
            File.WriteAllText(
                Path.Combine(runDirectory, "d-endpoint-stage.json"),
                "{\"status\":\"passed\",\"gate\":\"D4_LDN_TEARDOWN\"}\n", Utf8);
            var archivePath = Task.Run(() => session.ExportAsync(temporaryRoot)).GetAwaiter().GetResult();
            using var archive = ZipFile.OpenRead(archivePath);
            var names = archive.Entries.Select(entry => entry.FullName).ToArray();
            var evidence = string.Join("\n", archive.Entries
                .Where(entry => entry.Length > 0)
                .Select(entry =>
                {
                    using var reader = new StreamReader(entry.Open(), Utf8);
                    return reader.ReadToEnd();
                }));
            return evidence.Contains("application-session.v1", StringComparison.Ordinal) &&
                   evidence.Contains("사용자", StringComparison.Ordinal) &&
                   !evidence.Contains("private-value", StringComparison.Ordinal) &&
                   !evidence.Contains("ABC123", StringComparison.Ordinal) &&
                   !evidence.Contains("RADIO-A", StringComparison.Ordinal) &&
                   !evidence.Contains("00:11:22:33:44:55", StringComparison.Ordinal) &&
                   !evidence.Contains("nested-private", StringComparison.Ordinal) &&
                   names.Any(name => name.EndsWith(
                       "/worker-events.ndjson", StringComparison.Ordinal)) &&
                   names.Any(name => name.EndsWith(
                       "/d-endpoint-stage.json", StringComparison.Ordinal)) &&
                   ToWslPath(@"C:\Users\테스트 사용자\SwitchTrade").Equals(
                       "/mnt/c/Users/테스트 사용자/SwitchTrade", StringComparison.Ordinal);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or
                                      InvalidDataException or JsonException or ArgumentException)
        {
            return false;
        }
        finally
        {
            if (Path.GetFileName(temporaryRoot).StartsWith(
                    "SwitchTrade-session-selftest-", StringComparison.Ordinal) &&
                Directory.Exists(temporaryRoot))
            {
                try { Directory.Delete(temporaryRoot, recursive: true); }
                catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
            }
        }
    }

    private void AppendLine(
        string fileName, string line, bool terminalEvidence, long? fileLimit = null)
    {
        lock (_gate)
        {
            var path = Path.Combine(DirectoryPath, fileName);
            var bytes = Utf8.GetBytes(TrimLine(line) + Environment.NewLine);
            var currentFileSize = File.Exists(path) ? new FileInfo(path).Length : 0;
            var directorySize = DirectorySize(DirectoryPath);
            var allowedSessionSize = terminalEvidence ? SessionLimit : SessionLimit - TerminalReserve;
            if ((fileLimit.HasValue && currentFileSize + bytes.Length > fileLimit.Value) ||
                directorySize + bytes.Length > allowedSessionSize)
            {
                WriteTruncationMarker(path, currentFileSize, fileLimit ?? allowedSessionSize);
                return;
            }
            using var stream = new FileStream(path, FileMode.Append, FileAccess.Write, FileShare.ReadWrite);
            stream.Write(bytes);
            stream.Flush(flushToDisk: false);
        }
    }

    private void WriteManifest(string exitStatus, DateTimeOffset? endedUtc)
    {
        WriteJson("application-session.v1.json", new Dictionary<string, object?>
        {
            ["schema"] = "application-session.v1",
            ["app_session_id"] = Id,
            ["started_utc"] = Directory.GetCreationTimeUtc(DirectoryPath).ToString("O"),
            ["ended_utc"] = endedUtc?.ToString("O"),
            ["desktop_pid"] = Environment.ProcessId,
            ["product_version"] = Assembly.GetExecutingAssembly().GetName().Version?.ToString() ?? "unknown",
            ["release_id"] = ReadReleaseId(),
            ["runtime_identity"] = ReadRuntimeIdentity(),
            ["control_contract"] = ControlApiClient.ReadinessContract,
            ["exit_status"] = exitStatus,
            ["previous_abnormal_session"] = _previousAbnormalSession,
        });
    }

    private void WriteJson(string fileName, object value)
    {
        lock (_gate)
        {
            var path = Path.Combine(DirectoryPath, fileName);
            var temporary = path + ".tmp";
            File.WriteAllText(temporary, Redact(JsonSerializer.Serialize(value, Json)), Utf8);
            File.Move(temporary, path, overwrite: true);
        }
    }

    private string? FindPreviousAbnormalSession()
    {
        foreach (var directory in new DirectoryInfo(_root).EnumerateDirectories()
                     .Where(item => !item.Attributes.HasFlag(FileAttributes.ReparsePoint) &&
                                    !string.Equals(item.FullName, DirectoryPath, StringComparison.OrdinalIgnoreCase))
                     .OrderByDescending(item => item.Name))
        {
            var path = Path.Combine(directory.FullName, "application-session.v1.json");
            try
            {
                using var document = JsonDocument.Parse(File.ReadAllBytes(path));
                var root = document.RootElement;
                var status = root.TryGetProperty("exit_status", out var value) ? value.GetString() : null;
                if (status is null or "running" or "abnormal") return directory.Name;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
            {
                return directory.Name;
            }
        }
        return null;
    }

    private IEnumerable<string> ExportSessionDirectories()
    {
        yield return DirectoryPath;
        if (string.IsNullOrWhiteSpace(_previousAbnormalSession)) yield break;
        var previous = Path.GetFullPath(Path.Combine(_root, _previousAbnormalSession));
        if (Path.GetDirectoryName(previous)?.Equals(
                Path.GetFullPath(_root).TrimEnd(Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase) == true &&
            Directory.Exists(previous) &&
            !new DirectoryInfo(previous).Attributes.HasFlag(FileAttributes.ReparsePoint))
            yield return previous;
    }

    private static IEnumerable<string> EnumerateAllowedFiles(string directory)
    {
        foreach (var path in Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
                     .OrderBy(value => value, StringComparer.OrdinalIgnoreCase))
        {
            var info = new FileInfo(path);
            if (info.Attributes.HasFlag(FileAttributes.ReparsePoint)) continue;
            var relative = Path.GetRelativePath(directory, path);
            if (relative.StartsWith("..", StringComparison.Ordinal)) continue;
            var name = info.Name;
            if (name is "application-session.v1.json" or "failure-summary.v1.json" ||
                name.EndsWith("-events.jsonl", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".stdout.log", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".stderr.log", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("worker-events.ndjson", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith(".truncated", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("p0-side-ready.json", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith("-stage.json", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("d5-control-state.json", StringComparison.OrdinalIgnoreCase) ||
                name.Equals("d-local-release.json", StringComparison.OrdinalIgnoreCase) ||
                name.EndsWith("-report.json", StringComparison.OrdinalIgnoreCase) ||
                name.StartsWith("wsl-", StringComparison.OrdinalIgnoreCase) &&
                name.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                yield return path;
        }
    }

    private async Task<byte[]> ReadBoundedRedactedAsync(
        string path, long limit, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(
            path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete,
            64 * 1024, FileOptions.Asynchronous | FileOptions.SequentialScan);
        var truncated = stream.Length > limit;
        if (truncated) stream.Seek(-limit, SeekOrigin.End);
        using var memory = new MemoryStream();
        await stream.CopyToAsync(memory, cancellationToken);
        var text = Utf8.GetString(memory.ToArray());
        if (truncated) text = "[TRUNCATED: export retained bounded tail]" + Environment.NewLine + text;
        return Utf8.GetBytes(Redact(text));
    }

    private void ApplyRetention()
    {
        var protectedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            Path.GetFileName(DirectoryPath),
        };
        if (!string.IsNullOrWhiteSpace(_previousAbnormalSession))
            protectedNames.Add(_previousAbnormalSession);
        var directories = new DirectoryInfo(_root).EnumerateDirectories()
            .Where(item => !item.Attributes.HasFlag(FileAttributes.ReparsePoint))
            .OrderByDescending(item => item.Name).ToList();
        long total = directories.Sum(item => DirectorySize(item.FullName));
        var kept = directories.Count;
        foreach (var directory in directories.OrderBy(item => item.Name))
        {
            if ((kept <= SessionCountLimit && total <= RetentionLimit) ||
                protectedNames.Contains(directory.Name)) continue;
            var size = DirectorySize(directory.FullName);
            try
            {
                directory.Delete(recursive: true);
                total -= size;
                kept--;
            }
            catch (Exception error) when (error is IOException or UnauthorizedAccessException) { }
        }
    }

    private string Redact(string value)
    {
        var redacted = Secret.Replace(value, "$1$2[REDACTED]");
        redacted = Mac.Replace(redacted, "[REDACTED_MAC]");
        if (!string.IsNullOrWhiteSpace(_profile))
            redacted = redacted.Replace(_profile, "%USERPROFILE%", StringComparison.OrdinalIgnoreCase);
        return redacted;
    }

    private static string TrimLine(string value) =>
        value.Length <= LineLimit ? value : value[..LineLimit] + " [TRUNCATED_LINE]";

    private static bool IsOwnedStreamName(string value) => value is
        "control.stdout.log" or "control.stderr.log" or
        "wrapper.stdout.log" or "wrapper.stderr.log" or
        "endpoint.stdout.log" or "endpoint.stderr.log";

    private static void WriteTruncationMarker(string path, long current, long limit)
    {
        var markerPath = path + ".truncated";
        if (File.Exists(markerPath)) return;
        File.WriteAllText(markerPath,
            $"TRUNCATED current_bytes={current} limit_bytes={limit}{Environment.NewLine}", Utf8);
    }

    private static long DirectorySize(string path)
    {
        try
        {
            return Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories)
                .Select(file => new FileInfo(file))
                .Where(file => !file.Attributes.HasFlag(FileAttributes.ReparsePoint))
                .Sum(file => file.Length);
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException) { return 0; }
    }

    private static string ReadReleaseId() => ReadJsonValue(
        Path.Combine(AppContext.BaseDirectory, "release-manifest.json"), "release_id");

    private static string ReadRuntimeIdentity()
    {
        var path = Path.Combine(Environment.GetFolderPath(
            Environment.SpecialFolder.LocalApplicationData),
            "SwitchTrade", "state", "active-runtime.json");
        return ReadJsonValue(path, "active_runtime");
    }

    private static string ReadJsonValue(string path, string property)
    {
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(path));
            return document.RootElement.TryGetProperty(property, out var value)
                ? value.GetString() ?? "unknown" : "unknown";
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException)
        {
            return "unknown";
        }
    }
}
