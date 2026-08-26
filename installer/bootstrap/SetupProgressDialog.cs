using System.Diagnostics;
using System.Drawing;
using System.Windows.Forms;

namespace SwitchTrade.Setup;

internal sealed record SetupProcessResult(int ExitCode, string Output, string Error);

internal static class SetupProgressDialog
{
    public static SetupProcessResult Run(ProcessStartInfo start, string action)
    {
        SetupProcessResult? result = null;
        using var form = new Form
        {
            Text = "SwitchTrade Setup",
            StartPosition = FormStartPosition.CenterScreen,
            ClientSize = new Size(520, 190),
            MinimumSize = new Size(520, 190),
            MaximumSize = new Size(520, 190),
            ControlBox = false,
            BackColor = Color.FromArgb(246, 247, 249),
            Font = new Font("Segoe UI", 10),
            AutoScaleMode = AutoScaleMode.Dpi,
        };
        var title = new Label
        {
            Text = ActionTitle(action),
            AutoSize = true,
            Font = new Font("Segoe UI Semibold", 18),
            ForeColor = Color.FromArgb(25, 34, 48),
            Location = new Point(30, 26),
        };
        var status = new Label
        {
            Text = "This can take several minutes. Please keep this window open.",
            AutoSize = true,
            ForeColor = Color.FromArgb(57, 66, 82),
            Location = new Point(32, 76),
        };
        var progress = new ProgressBar
        {
            Style = ProgressBarStyle.Marquee,
            MarqueeAnimationSpeed = 25,
            Location = new Point(34, 116),
            Size = new Size(452, 22),
        };
        form.Controls.Add(title);
        form.Controls.Add(status);
        form.Controls.Add(progress);

        form.Shown += async (_, _) =>
        {
            try
            {
                using var process = Process.Start(start) ??
                    throw new InvalidOperationException("Setup did not start.");
                var outputTask = process.StandardOutput.ReadToEndAsync();
                var errorTask = process.StandardError.ReadToEndAsync();
                await process.WaitForExitAsync();
                result = new SetupProcessResult(process.ExitCode,
                    await outputTask, await errorTask);
            }
            catch (Exception error)
            {
                result = new SetupProcessResult(1, "", error.Message);
            }
            finally
            {
                form.Close();
            }
        };
        form.ShowDialog();
        return result ?? new SetupProcessResult(1, "", "Setup stopped unexpectedly.");
    }

    private static string ActionTitle(string action) => action.ToLowerInvariant() switch
    {
        "install" => "Installing SwitchTrade",
        "update" => "Updating SwitchTrade",
        "repair" => "Repairing SwitchTrade",
        "rollback" => "Rolling back SwitchTrade",
        "uninstall" => "Uninstalling SwitchTrade",
        _ => "Running SwitchTrade Setup",
    };
}
