using System.Diagnostics;
using System.Windows.Controls;
using System.Windows.Navigation;

namespace SwitchTrade.Desktop.Views;

public partial class SettingsView : UserControl
{
    public SettingsView() => InitializeComponent();

    private void OpenSupportPage(object sender, RequestNavigateEventArgs e)
    {
        Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
        e.Handled = true;
    }
}
