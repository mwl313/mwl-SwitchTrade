using System.ComponentModel;
using System.Diagnostics;
using System.Windows;
using System.Windows.Navigation;

namespace SwitchTrade.Desktop;

public partial class CreditsWindow : Window
{
    public CreditsWindow() => InitializeComponent();

    private void OpenExternalLink(object sender, RequestNavigateEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
        }
        catch (Exception error) when (error is Win32Exception or InvalidOperationException)
        {
            MessageBox.Show(this, "Windows could not open this link.", "SwitchTrade Credits",
                MessageBoxButton.OK, MessageBoxImage.Information);
        }
        e.Handled = true;
    }
}
