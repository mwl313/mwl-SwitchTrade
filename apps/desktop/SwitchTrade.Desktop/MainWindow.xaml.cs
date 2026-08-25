using System.Diagnostics;
using System.ComponentModel;
using System.IO;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Threading;

namespace SwitchTrade.Desktop;

public partial class MainWindow : Window
{
    public const string ApiBase = "http://127.0.0.1:8787";
    private readonly HttpClient _http = new() { BaseAddress = new Uri(ApiBase), Timeout = TimeSpan.FromSeconds(3) };
    private readonly DispatcherTimer _statusTimer = new() { Interval = TimeSpan.FromSeconds(2) };
    private string _screen = "main";
    private string _lobbyCode = "";
    private string _lobbyName = "";
    private string _lobbyRole = "host";
    private bool _sessionStarted;
    private bool _closing;

    public MainWindow()
    {
        InitializeComponent();
        ShowMain();
        _statusTimer.Tick += async (_, _) => await RefreshStatus();
        _statusTimer.Start();
        Loaded += async (_, _) =>
        {
            if (!await RefreshStatus()) TryStartInstalledBackend();
        };
        PreviewKeyDown += async (_, e) =>
        {
            if (e.Key != Key.Escape || _screen == "main") return;
            if (_screen == "lobby" && _sessionStarted)
            {
                try { await Post("/api/session/stop", new { }); } catch { }
                _sessionStarted = false;
            }
            ShowMain();
        };
        Closing += StopBeforeClose;
        Closed += (_, _) => _http.Dispose();
    }

    private static TextBlock Label(string text, double size = 14) => new()
    {
        Text = text,
        FontSize = size,
        FontWeight = FontWeights.SemiBold,
        Foreground = new SolidColorBrush(Color.FromRgb(23, 49, 42)),
        Margin = new Thickness(0, 0, 0, 7),
        TextWrapping = TextWrapping.Wrap,
    };

    private static Button Action(string text, RoutedEventHandler click)
    {
        var button = new Button { Content = $"▶  {text}" };
        button.Click += click;
        return button;
    }

    private void SetScreen(string id, string title, string hint, UIElement content)
    {
        _screen = id;
        ScreenTitle.Text = title;
        HintText.Text = hint;
        ScreenContent.Content = content;
        Dispatcher.BeginInvoke(() => (content as Panel)?.Children.OfType<Control>().FirstOrDefault()?.Focus(),
            DispatcherPriority.Input);
    }

    private void ShowMain()
    {
        var panel = new StackPanel();
        panel.Children.Add(Action("HOST A TRADE GROUP", (_, _) => ShowHost()));
        panel.Children.Add(Action("JOIN A TRADE GROUP", (_, _) => ShowJoin()));
        panel.Children.Add(Action("CONFIGURATION", async (_, _) => await ShowConfiguration()));
        panel.Children.Add(Label("Private passcode groups are the beta path. Public rooms are demonstrative.", 13));
        SetScreen("main", "LINK DESK", "Choose how you want to connect.", panel);
    }

    private void ShowHost()
    {
        var name = new TextBox { Text = "MY TRADE GROUP", MaxLength = 22 };
        var visibility = new ComboBox { ItemsSource = new[] { "PRIVATE", "PUBLIC" }, SelectedIndex = 0 };
        var error = Label("", 13);
        error.Foreground = (Brush)FindResource("Danger");
        var panel = new StackPanel();
        panel.Children.Add(Label("GROUP NAME"));
        panel.Children.Add(name);
        panel.Children.Add(Label("VISIBILITY"));
        panel.Children.Add(visibility);
        panel.Children.Add(Action("CREATE GROUP", async (_, _) =>
        {
            try
            {
                var result = await Post("/api/groups", new
                {
                    name = string.IsNullOrWhiteSpace(name.Text) ? "MY TRADE GROUP" : name.Text.Trim(),
                    visibility = visibility.Text.ToLowerInvariant(),
                });
                var group = result.GetProperty("group");
                ShowLobby("host", group.GetProperty("name").GetString()!, group.GetProperty("passcode").GetString()!);
            }
            catch (Exception ex) { error.Text = ex.Message; }
        }));
        panel.Children.Add(Action("BACK", (_, _) => ShowMain()));
        panel.Children.Add(error);
        SetScreen("host", "HOST GROUP", "Create the online group before opening the Switch room.", panel);
    }

    private void ShowJoin()
    {
        var code = new TextBox { MaxLength = 8, CharacterCasing = CharacterCasing.Upper };
        var error = Label("", 13);
        error.Foreground = (Brush)FindResource("Danger");
        var panel = new StackPanel();
        panel.Children.Add(Label("PRIVATE GROUP PASSCODE"));
        panel.Children.Add(code);
        panel.Children.Add(Action("JOIN PRIVATE GROUP", async (_, _) =>
        {
            try
            {
                var result = await Post("/api/groups/join", new { passcode = code.Text.Trim() });
                var group = result.GetProperty("group");
                ShowLobby("guest", group.GetProperty("name").GetString()!, group.GetProperty("passcode").GetString()!);
            }
            catch (Exception ex) { error.Text = ex.Message; }
        }));
        panel.Children.Add(Action("BROWSE PUBLIC GROUPS (DEMO)", (_, _) => ShowPublic()));
        panel.Children.Add(Action("BACK", (_, _) => ShowMain()));
        panel.Children.Add(error);
        SetScreen("join", "JOIN GROUP", "Use the passcode shared by the host.", panel);
    }

    private void ShowPublic()
    {
        var panel = new StackPanel();
        panel.Children.Add(Label("Public matchmaking is not connected in beta. These entries demonstrate the final layout.", 13));
        foreach (var room in new[] { "MAY'S TRADE ROOM    OPEN", "KANTO LINK CLUB     WAIT", "NIGHT TRADES        OPEN" })
            panel.Children.Add(new Button { Content = room, IsEnabled = false });
        panel.Children.Add(Action("BACK", (_, _) => ShowJoin()));
        SetScreen("public", "PUBLIC GROUPS — DEMO", "Private groups are functional; public service is backlog.", panel);
    }

    private void ShowLobby(string role, string name, string code)
    {
        _lobbyRole = role;
        _lobbyName = name;
        _lobbyCode = code;
        _sessionStarted = false;
        RenderLobby();
    }

    private void RenderLobby(string message = "NOT READY")
    {
        var state = Label(message, 16);
        state.Foreground = (Brush)FindResource(_sessionStarted ? "EmeraldDark" : "Danger");
        var panel = new StackPanel();
        panel.Children.Add(Label(_lobbyName, 22));
        panel.Children.Add(Label($"PASSCODE  {_lobbyCode}", 18));
        panel.Children.Add(Label($"{_lobbyRole.ToUpperInvariant()} ENDPOINT"));
        panel.Children.Add(state);
        panel.Children.Add(Action(_sessionStarted ? "CANCEL READY" : "I AM READY", async (_, _) =>
        {
            try
            {
                if (_sessionStarted)
                {
                    await Post("/api/session/stop", new { });
                    _sessionStarted = false;
                    RenderLobby();
                }
                else
                {
                    await Post("/api/session/start", new { role = _lobbyRole, passcode = _lobbyCode });
                    _sessionStarted = true;
                    RenderLobby("STARTING RADIO AND TUNNEL…");
                }
            }
            catch (Exception ex) { RenderLobby(ex.Message); }
        }));
        panel.Children.Add(Action("LEAVE GROUP", async (_, _) =>
        {
            if (_sessionStarted) try { await Post("/api/session/stop", new { }); } catch { }
            ShowMain();
        }));
        SetScreen("lobby", "TRADE GROUP LOBBY", "Share the passcode, then prepare each Switch.", panel);
    }

    private async Task ShowConfiguration()
    {
        var panel = new StackPanel();
        try
        {
            var response = await _http.GetAsync("/api/hardware/profiles");
            response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            foreach (var profile in document.RootElement.GetProperty("profiles").EnumerateArray())
            {
                var id = profile.GetProperty("usb_id").GetString()!.ToUpperInvariant();
                var status = profile.GetProperty("status").GetString()!.ToUpperInvariant();
                var roles = string.Join(", ", profile.GetProperty("roles").EnumerateArray().Select(x => x.GetString()));
                panel.Children.Add(Label($"ADAPTER  {id}", 17));
                panel.Children.Add(Label($"{status}  ·  {roles.ToUpperInvariant()}", 13));
                panel.Children.Add(new Separator { Margin = new Thickness(0, 8, 0, 14) });
            }
        }
        catch (Exception ex) { panel.Children.Add(Label($"BACKEND OFFLINE\n{ex.Message}", 14)); }
        panel.Children.Add(Action("RECHECK", async (_, _) => await ShowConfiguration()));
        panel.Children.Add(Action("BACK", (_, _) => ShowMain()));
        SetScreen("configuration", "CONFIGURATION", "Hardware policy comes from the shared driver profile registry.", panel);
    }

    private async Task<JsonElement> Post(string path, object body)
    {
        using var response = await _http.PostAsJsonAsync(path, body);
        var json = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode)
        {
            try
            {
                using var problem = JsonDocument.Parse(json);
                throw new InvalidOperationException(problem.RootElement.GetProperty("detail").GetString());
            }
            catch (JsonException) { throw new InvalidOperationException($"Request failed ({(int)response.StatusCode})"); }
        }
        using var document = JsonDocument.Parse(json);
        return document.RootElement.Clone();
    }

    private async Task<bool> RefreshStatus()
    {
        try
        {
            var response = await _http.GetAsync("/api/status");
            response.EnsureSuccessStatusCode();
            using var document = JsonDocument.Parse(await response.Content.ReadAsStringAsync());
            var status = document.RootElement.GetProperty("status").GetString() ?? "READY";
            StatusText.Text = status.Replace('_', ' ').ToUpperInvariant();
            StatusLight.Fill = new SolidColorBrush(Color.FromRgb(76, 195, 151));
            return true;
        }
        catch
        {
            StatusText.Text = "BACKEND OFFLINE";
            StatusLight.Fill = new SolidColorBrush(Color.FromRgb(210, 100, 89));
            return false;
        }
    }

    private async void StopBeforeClose(object? sender, CancelEventArgs e)
    {
        if (_closing || !_sessionStarted) return;
        e.Cancel = true;
        try { await Post("/api/session/stop", new { }); } catch { }
        _sessionStarted = false;
        _closing = true;
        Close();
    }

    private static void TryStartInstalledBackend()
    {
        var launcher = Path.Combine(AppContext.BaseDirectory, "installer", "Launch-SwitchTrade.ps1");
        if (!File.Exists(launcher)) return;
        Process.Start(new ProcessStartInfo
        {
            FileName = "powershell.exe",
            Arguments = $"-NoProfile -ExecutionPolicy Bypass -File \"{launcher}\" -NoBrowser",
            UseShellExecute = true,
            WindowStyle = ProcessWindowStyle.Hidden,
        });
    }
}
