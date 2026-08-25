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
        YouPartyColumn.Width = stacked ? new GridLength(1, GridUnitType.Star) : new GridLength(1, GridUnitType.Star);
        PartyGutterColumn.Width = stacked ? new GridLength(0) : new GridLength(18);
        PartnerPartyColumn.Width = stacked ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
        PartyRowGutter.Height = stacked ? new GridLength(18) : new GridLength(0);
        Grid.SetColumn(YouPartyGrid, 0);
        Grid.SetRow(YouPartyGrid, stacked ? 2 : 0);
        Grid.SetColumn(PartnerPartyGrid, stacked ? 0 : 2);
        Grid.SetRow(PartnerPartyGrid, 0);
    }
}
