using System.Windows;

namespace SwitchTrade.Desktop;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--self-test"))
        {
            Shutdown(new Uri(SwitchTrade.Desktop.MainWindow.ApiBase).IsLoopback ? 0 : 1);
            return;
        }
        new MainWindow().Show();
    }
}
