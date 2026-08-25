using System.ComponentModel;
using System.Windows;
using System.Windows.Input;
using System.Windows.Threading;
using SwitchTrade.Desktop.Services;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop;

public partial class MainWindow : Window
{
    public const string ApiBase = ControlApiClient.ApiBase;

    private readonly MainViewModel _viewModel;
    private readonly DispatcherTimer _statusTimer = new() { Interval = TimeSpan.FromSeconds(2) };
    private bool _allowClose;

    public MainWindow()
    {
        InitializeComponent();
        _viewModel = new MainViewModel(
            new ControlApiClient(),
            new BackendLauncher(),
            new WindowsDialogService(),
            new WindowsClipboardService(),
            new PublicRoomPreviewProvider());
        DataContext = _viewModel;

        Loaded += async (_, _) => await _viewModel.InitializeAsync();
        _statusTimer.Tick += async (_, _) => await _viewModel.RefreshAsync();
        _statusTimer.Start();
        PreviewKeyDown += HandleGlobalKey;
        Closing += ConfirmClose;
        Closed += (_, _) =>
        {
            _statusTimer.Stop();
            _viewModel.Dispose();
        };
    }

    private async void HandleGlobalKey(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.OemComma && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            _viewModel.OpenSettings();
            e.Handled = true;
        }
        else if (e.Key == Key.F5)
        {
            await _viewModel.RefreshAsync();
            e.Handled = true;
        }
        else if (e.Key == Key.Escape ||
                 (e.Key == Key.Left && Keyboard.Modifiers.HasFlag(ModifierKeys.Alt)))
        {
            if (!_viewModel.DismissTemporaryLayer())
                await _viewModel.GoBackAsync();
            e.Handled = true;
        }
    }

    private async void ConfirmClose(object? sender, CancelEventArgs e)
    {
        if (_allowClose) return;
        e.Cancel = true;
        if (!await _viewModel.CanCloseAsync()) return;
        _allowClose = true;
        Close();
    }
}
