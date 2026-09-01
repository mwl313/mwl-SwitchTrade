using System.Windows.Controls;
using SwitchTrade.Desktop.Models;
using SwitchTrade.Desktop.ViewModels;
namespace SwitchTrade.Desktop.Views;
public partial class HomeView : UserControl
{
    public HomeView() => InitializeComponent();

    private async void AdapterSelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (!IsLoaded || DataContext is not HomeScreenViewModel viewModel) return;
        viewModel.SelectedDevice = (sender as ComboBox)?.SelectedItem as HardwareDeviceViewData;
        await viewModel.UseSelectedAdapterAsync();
    }
}
