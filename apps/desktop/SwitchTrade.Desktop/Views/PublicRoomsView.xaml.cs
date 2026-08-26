using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop.Views;

public partial class PublicRoomsView : UserControl
{
    private bool _compact;

    public PublicRoomsView() => InitializeComponent();

    private void ViewLoaded(object sender, RoutedEventArgs e) => UpdateLayoutState();
    private void ViewSizeChanged(object sender, SizeChangedEventArgs e) => UpdateLayoutState();
    private void RoomSelectionChanged(object sender, SelectionChangedEventArgs e) => UpdateCompactDetails();

    private void UpdateLayoutState()
    {
        _compact = ActualWidth < 900;
        DetailsColumn.Width = _compact ? new GridLength(0) : new GridLength(360);
        DetailsGutter.Width = _compact ? new GridLength(0) : new GridLength(20);
        WideDetails.Visibility = _compact ? Visibility.Collapsed : Visibility.Visible;
        UpdateCompactDetails();
    }

    private void UpdateCompactDetails()
    {
        CompactDetails.Visibility = _compact && DataContext is PublicRoomsScreenViewModel { HasSelection: true }
            ? Visibility.Visible : Visibility.Collapsed;
    }

    private void ViewKeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.K && Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
        {
            SearchField.Focus();
            e.Handled = true;
            return;
        }
        if (e.Key == Key.Escape && CompactDetails.Visibility == Visibility.Visible &&
            DataContext is PublicRoomsScreenViewModel viewModel)
        {
            viewModel.CloseDetailsCommand.Execute(null);
            UpdateCompactDetails();
            e.Handled = true;
        }
    }
}
