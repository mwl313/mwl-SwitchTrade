using System.Diagnostics;
using System.Drawing;
using System.ComponentModel;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace SwitchTrade.Setup;

internal sealed record RadioChoice(string BusId, string UsbId, string InstanceId, string Name, bool Experimental)
{
    public override string ToString() =>
        $"{Name} · USB {BusId}" + (Experimental ? " · Experimental" : "");
}

internal sealed record SetupChoice(
    string Action,
    bool AcceptPrerequisiteChanges,
    bool AcceptGlobalKernelChange,
    bool AcceptVmwareRelease,
    bool DeferHardwareSetup,
    bool PurgeDistro,
    RadioChoice? Radio);

internal static class SetupDialog
{
    public static SetupChoice? Show(string packageRoot)
    {
        var kernelPresent = File.Exists(Path.Combine(packageRoot, "payload", "kernel", "kernel"));
        var installed = Directory.Exists(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "SwitchTrade"));
        var rollbackPresent = Directory.Exists(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "SwitchTrade.previous"));
        var radios = DetectRadios(packageRoot);
        using var form = new Form
        {
            Text = "SwitchTrade Setup",
            StartPosition = FormStartPosition.CenterScreen,
            ClientSize = new Size(680, 650),
            MinimumSize = new Size(680, 650),
            MaximizeBox = false,
            BackColor = Color.FromArgb(246, 247, 249),
            Font = new Font("Segoe UI", 10),
            AutoScaleMode = AutoScaleMode.Dpi,
        };
        var panel = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            Padding = new Padding(36, 28, 36, 28),
            ColumnCount = 1,
            RowCount = 10,
            AutoScroll = true,
        };
        panel.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));

        var title = new Label
        {
            Text = "Set up SwitchTrade",
            AutoSize = true,
            Font = new Font("Segoe UI Semibold", 22),
            ForeColor = Color.FromArgb(25, 34, 48),
            Margin = new Padding(0, 0, 0, 6),
        };
        var intro = Label(
            "SwitchTrade installs one isolated WSL distribution and connects a supported USB Wi-Fi adapter. " +
            "It does not reset or remove your other WSL distributions. Keep all extracted setup files " +
            "together until Setup finishes.");
        intro.Margin = new Padding(0, 0, 0, 20);

        var actionLabel = Heading("Setup action");
        var action = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 280 };
        action.Items.Add(installed ? "Update" : "Install");
        action.Items.Add("Repair");
        if (rollbackPresent) action.Items.Add("Rollback");
        action.Items.Add("Uninstall");
        action.SelectedIndex = 0;

        var prerequisites = new CheckBox
        {
            Text = "Allow Setup to enable or update WSL 2 and install the pinned USB/IP prerequisite if needed",
            AutoSize = true,
            Margin = new Padding(0, 12, 0, 8),
        };
        var kernel = new CheckBox
        {
            Text = "I understand the packaged custom kernel changes the global WSL 2 kernel selection",
            AutoSize = true,
            Enabled = kernelPresent,
            Checked = !kernelPresent,
            Margin = new Padding(0, 0, 0, 8),
        };
        var vmware = new CheckBox
        {
            Text = "Allow Setup to release VMware USB ownership if it blocks the selected adapter",
            AutoSize = true,
            Margin = new Padding(0, 0, 0, 18),
        };

        var radioLabel = Heading("Wi-Fi adapter");
        var radio = new ComboBox { DropDownStyle = ComboBoxStyle.DropDownList, Width = 560 };
        radio.Items.Add("Configure an adapter later in SwitchTrade Settings");
        foreach (var item in radios) radio.Items.Add(item);
        radio.SelectedIndex = radios.Count == 1 ? 1 : 0;
        var radioNote = Label(radios.Count == 0
            ? "No selectable profiled adapter is currently visible. Installation can finish now; run Setup Repair after connecting one."
            : "Experimental adapters are selectable without repeated confirmation, but they are untested and may not connect reliably.");
        radioNote.ForeColor = Color.FromArgb(86, 96, 112);
        radioNote.Margin = new Padding(0, 6, 0, 12);
        var purge = new CheckBox
        {
            Text = "Also remove the named SwitchTrade WSL distribution during uninstall",
            AutoSize = true,
            Visible = false,
            Margin = new Padding(0, 0, 0, 12),
        };

        var warning = Label(
            "The previous .wslconfig is backed up and restored during rollback or uninstall. " +
            "Setup never unregisters an unrelated distribution.");
        warning.BackColor = Color.FromArgb(232, 239, 255);
        warning.Padding = new Padding(14);
        warning.Margin = new Padding(0, 8, 0, 20);

        var buttons = new FlowLayoutPanel
        {
            FlowDirection = FlowDirection.RightToLeft,
            Dock = DockStyle.Fill,
            AutoSize = true,
            WrapContents = false,
        };
        var primary = Button("Continue", Color.FromArgb(47, 91, 210), Color.White);
        var cancel = Button("Cancel", Color.White, Color.FromArgb(38, 48, 64));
        cancel.FlatAppearance.BorderColor = Color.FromArgb(185, 192, 204);
        cancel.DialogResult = DialogResult.Cancel;
        buttons.Controls.Add(primary);
        buttons.Controls.Add(cancel);

        panel.Controls.Add(title);
        panel.Controls.Add(intro);
        panel.Controls.Add(actionLabel);
        panel.Controls.Add(action);
        panel.Controls.Add(prerequisites);
        panel.Controls.Add(kernel);
        panel.Controls.Add(vmware);
        panel.Controls.Add(radioLabel);
        panel.Controls.Add(radio);
        panel.Controls.Add(radioNote);
        panel.Controls.Add(purge);
        panel.Controls.Add(warning);
        panel.Controls.Add(buttons);
        form.Controls.Add(panel);
        form.CancelButton = cancel;

        void Refresh()
        {
            var selected = action.SelectedItem?.ToString() ?? "Install";
            var mutatingInstall = selected is "Install" or "Update" or "Repair";
            prerequisites.Visible = mutatingInstall;
            kernel.Visible = mutatingInstall && kernelPresent;
            vmware.Visible = mutatingInstall;
            radioLabel.Visible = mutatingInstall;
            radio.Visible = mutatingInstall;
            radioNote.Visible = mutatingInstall;
            purge.Visible = selected == "Uninstall";
            primary.Text = selected;
            primary.Enabled = !mutatingInstall || (prerequisites.Checked && kernel.Checked);
        }
        action.SelectedIndexChanged += (_, _) => Refresh();
        prerequisites.CheckedChanged += (_, _) => Refresh();
        kernel.CheckedChanged += (_, _) => Refresh();
        primary.Click += (_, _) => form.DialogResult = DialogResult.OK;
        Refresh();

        if (form.ShowDialog() != DialogResult.OK) return null;
        var selectedAction = action.SelectedItem?.ToString() ?? "Install";
        var selectedRadio = radio.SelectedItem as RadioChoice;
        return new SetupChoice(
            selectedAction, prerequisites.Checked, kernel.Checked, vmware.Checked,
            selectedRadio is null, purge.Checked, selectedRadio);
    }

    private static List<RadioChoice> DetectRadios(string packageRoot)
    {
        var profiles = Path.Combine(packageRoot, "payload", "app", "config", "wsl-radio-hardware.tsv");
        if (!File.Exists(profiles)) return [];
        var supported = File.ReadLines(profiles)
            .Where(line => !string.IsNullOrWhiteSpace(line) && !line.StartsWith('#'))
            .Select(line => line.Split('\t'))
            .Where(columns => columns.Length >= 8 && columns[5] != "quarantined" &&
                              (columns.Length < 11 || columns[10] == "ldn"))
            .ToDictionary(columns => columns[0].ToLowerInvariant(),
                columns => columns[5] is "upstream-candidate" or "driver-candidate");
        try
        {
            var start = new ProcessStartInfo("usbipd.exe", "state")
            {
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using var process = Process.Start(start);
            if (process is null) return [];
            var output = process.StandardOutput.ReadToEnd();
            process.WaitForExit(5000);
            if (!process.HasExited || process.ExitCode != 0) return [];
            using var state = JsonDocument.Parse(output);
            var result = new List<RadioChoice>();
            foreach (var device in state.RootElement.GetProperty("Devices").EnumerateArray())
            {
                var busId = device.GetProperty("BusId").GetString();
                var instance = device.GetProperty("InstanceId").GetString() ?? "";
                var match = Regex.Match(instance, @"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})",
                    RegexOptions.IgnoreCase);
                if (busId is null || !match.Success) continue;
                var usbId = $"{match.Groups[1].Value}:{match.Groups[2].Value}".ToLowerInvariant();
                if (!supported.TryGetValue(usbId, out var experimental)) continue;
                var name = device.GetProperty("Description").GetString() ?? usbId;
                result.Add(new RadioChoice(busId, usbId, instance, name, experimental));
            }
            return result;
        }
        catch (IOException) { return []; }
        catch (Win32Exception) { return []; }
        catch (InvalidOperationException) { return []; }
        catch (JsonException) { return []; }
    }

    private static Label Heading(string text) => new()
    {
        Text = text,
        AutoSize = true,
        Font = new Font("Segoe UI Semibold", 11),
        ForeColor = Color.FromArgb(25, 34, 48),
        Margin = new Padding(0, 6, 0, 6),
    };

    private static Label Label(string text) => new()
    {
        Text = text,
        AutoSize = true,
        MaximumSize = new Size(590, 0),
        ForeColor = Color.FromArgb(57, 66, 82),
    };

    private static Button Button(string text, Color background, Color foreground) => new()
    {
        Text = text,
        AutoSize = true,
        MinimumSize = new Size(112, 40),
        BackColor = background,
        ForeColor = foreground,
        FlatStyle = FlatStyle.Flat,
        Margin = new Padding(8, 0, 0, 0),
        UseVisualStyleBackColor = false,
    };
}
