using System.Windows;
using System.Windows.Controls;

namespace SwitchTrade.Desktop.Views;

public partial class TradeRoomView : UserControl
{
    public TradeRoomView() => InitializeComponent();
    private void ViewLoaded(object sender, RoutedEventArgs e) => UpdateLayoutState();
    private void ViewSizeChanged(object sender, SizeChangedEventArgs e) => UpdateLayoutState();

    private void UpdateLayoutState()
    {
        var stacked = ActualWidth < 776;
        LiveYouPartyColumn.Width = new GridLength(1, GridUnitType.Star);
        LivePartyGutterColumn.Width = stacked ? new GridLength(0) : new GridLength(18);
        LivePartnerPartyColumn.Width = stacked ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
        LivePartyRowGutter.Height = stacked ? new GridLength(18) : new GridLength(0);
        Grid.SetColumn(LiveYouPartyGrid, 0);
        Grid.SetRow(LiveYouPartyGrid, stacked ? 2 : 0);
        Grid.SetColumn(LivePartnerPartyGrid, stacked ? 0 : 2);
        Grid.SetRow(LivePartnerPartyGrid, 0);
    }
}
