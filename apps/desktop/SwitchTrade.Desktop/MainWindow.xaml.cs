using System.ComponentModel;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;
using SwitchTrade.Desktop.Services;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop;

[System.Diagnostics.CodeAnalysis.SuppressMessage(
    "Design", "CA1001:Types that own disposable fields should be disposable",
    Justification = "WPF owns the Window lifetime; WindowClosed deterministically disposes the view model.")]
public partial class MainWindow : Window
{
    public const string ApiBase = ControlApiClient.ApiBase;

    private readonly MainViewModel _viewModel;
    private readonly ApplicationSession _applicationSession;
    private readonly DispatcherTimer _statusTimer = new() { Interval = TimeSpan.FromSeconds(2) };
    private bool _allowClose;

    public MainWindow(ApplicationSession applicationSession)
    {
        InitializeComponent();
        _applicationSession = applicationSession;
        _viewModel = new MainViewModel(
            new ControlApiClient(),
            new BackendLauncher(applicationSession),
            new WindowsDialogService(),
            new WindowsClipboardService(),
            applicationSession: applicationSession);
        DataContext = _viewModel;

        Loaded += WindowLoaded;
        SizeChanged += WindowSizeChanged;
        KeyDown += HandleGlobalKey;
        _viewModel.PropertyChanged += ViewModelPropertyChanged;
        _statusTimer.Tick += async (_, _) => await _viewModel.RefreshAsync();
        Closing += ConfirmClose;
        Closed += WindowClosed;
    }

    private async void WindowLoaded(object sender, RoutedEventArgs e)
    {
        var work = SystemParameters.WorkArea;
        Width = Math.Min(Width, Math.Max(MinWidth, work.Width - 24));
        Height = Math.Min(Height, Math.Max(MinHeight, work.Height - 24));
        UpdateShellMargins();
        await _viewModel.InitializeAsync();
        _statusTimer.Start();
    }

    private void WindowSizeChanged(object sender, SizeChangedEventArgs e) => UpdateShellMargins();

    private void UpdateShellMargins()
    {
        const double left = 24;
        const double right = 24;
        HeaderContent.Margin = new Thickness(left, 0, right, 0);
        BackButton.Margin = new Thickness(left - 10, 0, 0, 0);
        CreditsButton.Margin = new Thickness(left - 10, 0, 0, 4);
        ScenePresenter.Margin = new Thickness(left, 12, right, 16);
        ScenePresenter.Width = Math.Min(ScenePresenter.MaxWidth, Math.Max(0, ActualWidth - left - right));
    }

    private void ViewModelPropertyChanged(object? sender, PropertyChangedEventArgs e)
    {
        if (e.PropertyName != nameof(MainViewModel.CurrentScreen)) return;
        Dispatcher.BeginInvoke(() => FindInitialFocus(ScenePresenter)?.Focus(), DispatcherPriority.Input);
    }

    private static Control? FindInitialFocus(DependencyObject root)
    {
        for (var index = 0; index < VisualTreeHelper.GetChildrenCount(root); index++)
        {
            var child = VisualTreeHelper.GetChild(root, index);
            if (child is Control { Focusable: true, IsEnabled: true, IsVisible: true, IsTabStop: true } control &&
                control is Button or TextBox or ComboBox or RadioButton or ListBox)
                return control;
            var nested = FindInitialFocus(child);
            if (nested is not null) return nested;
        }
        return null;
    }

    private async void HandleGlobalKey(object sender, KeyEventArgs e)
    {
        if (e.Handled) return;
        if (e.Key == Key.OemComma && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            await _viewModel.OpenSettingsAsync();
            e.Handled = true;
        }
        else if (e.Key == Key.F5)
        {
            await _viewModel.RefreshAsync();
            e.Handled = true;
        }
        else if (e.Key == Key.Escape)
        {
            if (_viewModel.DismissTemporaryLayer()) e.Handled = true;
            else if (_viewModel.CanGoBack)
            {
                await _viewModel.GoBackAsync();
                e.Handled = true;
            }
        }
        else if (e.Key == Key.Left && Keyboard.Modifiers.HasFlag(ModifierKeys.Alt))
        {
            await _viewModel.GoBackAsync();
            e.Handled = true;
        }
    }

    private async void ConfirmClose(object? sender, CancelEventArgs e)
    {
        if (_allowClose) return;
        e.Cancel = true;
        if (!await _viewModel.CanCloseAsync()) return;
        await BackendLauncher.StopAsync(_applicationSession);
        _allowClose = true;
        Close();
    }

    private void WindowClosed(object? sender, EventArgs e)
    {
        _statusTimer.Stop();
        _viewModel.PropertyChanged -= ViewModelPropertyChanged;
        _viewModel.Dispose();
    }

    private void OpenCredits(object sender, RoutedEventArgs e) =>
        new CreditsWindow { Owner = this }.ShowDialog();
}
