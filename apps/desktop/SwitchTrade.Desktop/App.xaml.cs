using System.Windows;
using SwitchTrade.Desktop.Services;
using SwitchTrade.Desktop.ViewModels;

namespace SwitchTrade.Desktop;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);
        if (e.Args.Contains("--self-test"))
        {
            var apiIsLocal = new Uri(ControlApiClient.ApiBase).IsLoopback;
            var codeNormalizes = JoinPrivateRoomScreenViewModel.NormalizeCode("ab-12 cd") == "AB12CD";
            var previewsAreExplicit = new PublicRoomPreviewProvider().GetRooms() is { Count: >= 3 } rooms &&
                                      rooms.All(room => room.RoomId.StartsWith("demo-", StringComparison.Ordinal));
            var requiredRoomFieldsWork =
                !CreateTradeRoomScreenViewModel.RequiredFieldsComplete("Room", "Trainer", "None", "English") &&
                !CreateTradeRoomScreenViewModel.RequiredFieldsComplete("Room", "Trainer", "FireRed", "None") &&
                CreateTradeRoomScreenViewModel.RequiredFieldsComplete("Room", "Trainer", "FireRed", "English");
            Shutdown(apiIsLocal && codeNormalizes && previewsAreExplicit && requiredRoomFieldsWork ? 0 : 1);
            return;
        }
        new MainWindow().Show();
    }
}
