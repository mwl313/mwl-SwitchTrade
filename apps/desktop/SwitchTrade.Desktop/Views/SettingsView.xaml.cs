using System.Windows;
using System.Windows.Controls;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop.Views;

public partial class SettingsView : UserControl
{
    public SettingsView() => InitializeComponent();

    private void ViewLoaded(object sender, RoutedEventArgs e)
    {
        UpdateLayoutState();
        if (DataContext is SettingsScreenViewModel viewModel)
        {
            viewModel.PropertyChanged -= ViewModelPropertyChanged;
            viewModel.PropertyChanged += ViewModelPropertyChanged;
        }
        UpdateSection();
    }

    private void ViewUnloaded(object sender, RoutedEventArgs e)
    {
        if (DataContext is SettingsScreenViewModel viewModel)
            viewModel.PropertyChanged -= ViewModelPropertyChanged;
    }

    private void ViewSizeChanged(object sender, SizeChangedEventArgs e) => UpdateLayoutState();
    private void ViewModelPropertyChanged(object? sender, System.ComponentModel.PropertyChangedEventArgs e)
    {
        if (e.PropertyName == nameof(SettingsScreenViewModel.SelectedSection)) UpdateSection();
    }

    private void UpdateLayoutState()
    {
        var compact = ActualWidth < 776;
        NavigationRail.Visibility = compact ? Visibility.Collapsed : Visibility.Visible;
        CompactSelector.Visibility = compact ? Visibility.Visible : Visibility.Collapsed;
        RailColumn.Width = compact ? new GridLength(0) : new GridLength(168);
        RailGutter.Width = compact ? new GridLength(0) : new GridLength(24);
    }

    private void UpdateSection()
    {
        var section = DataContext is SettingsScreenViewModel viewModel
            ? viewModel.SelectedSection : SettingsSection.Connection;
        ConnectionSection.Visibility = section == SettingsSection.Connection ? Visibility.Visible : Visibility.Collapsed;
        SupportSection.Visibility = section == SettingsSection.Support ? Visibility.Visible : Visibility.Collapsed;
        AdvancedSection.Visibility = section == SettingsSection.Advanced ? Visibility.Visible : Visibility.Collapsed;
    }
}
