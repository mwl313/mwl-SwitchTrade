using System.Diagnostics;
using System.IO;
using System.Windows;

namespace SwitchTrade.Desktop.Services;

public sealed class BackendLauncher
{
    public bool TryStart()
    {
        var candidates = new[]
        {
            Path.Combine(AppContext.BaseDirectory, "installer", "Launch-SwitchTrade.ps1"),
            Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "..", "installer", "Launch-SwitchTrade.ps1")),
        };
        var launcher = candidates.FirstOrDefault(File.Exists);
        if (launcher is null) return false;
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = "powershell.exe",
                Arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{launcher}\" -NoBrowser",
                UseShellExecute = true,
                WindowStyle = ProcessWindowStyle.Hidden,
            });
            return true;
        }
        catch (InvalidOperationException) { return false; }
        catch (System.ComponentModel.Win32Exception) { return false; }
    }
}

public interface IDialogService
{
    bool Confirm(string title, string message, string confirmText = "Continue");
}

public sealed class WindowsDialogService : IDialogService
{
    public bool Confirm(string title, string message, string confirmText = "Continue") =>
        MessageBox.Show(message, title, MessageBoxButton.OKCancel, MessageBoxImage.Warning) == MessageBoxResult.OK;
}

public interface IClipboardService
{
    void SetText(string text);
}

public sealed class WindowsClipboardService : IClipboardService
{
    public void SetText(string text)
    {
        if (!string.IsNullOrWhiteSpace(text)) Clipboard.SetText(text);
    }
}
