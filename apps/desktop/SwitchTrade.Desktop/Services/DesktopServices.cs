using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;

namespace SwitchTrade.Desktop.Services;

public sealed class BackendLauncher
{
    [System.Diagnostics.CodeAnalysis.SuppressMessage(
        "Performance", "CA1822:Mark members as static",
        Justification = "The launcher is an injected service boundary and may gain platform state.")]
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
        catch (Win32Exception) { return false; }
    }
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
            FontFamily = new FontFamily("Segoe UI Variable Text, Segoe UI"),
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
            FontFamily = new FontFamily("Segoe UI Variable Display, Segoe UI"),
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
