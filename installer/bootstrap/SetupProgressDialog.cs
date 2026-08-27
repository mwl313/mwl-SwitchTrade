using System.Diagnostics;
using System.Drawing;
using System.Text;
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
                var outputTask = ReadLinesAsync(process.StandardOutput, line =>
                {
                    var stage = ParseProgressStage(line);
                    if (stage is not null) status.Text = StageDescription(stage);
                });
                var errorTask = ReadLinesAsync(process.StandardError);
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
        "resume" => "Continuing SwitchTrade setup",
        "update" => "Updating SwitchTrade",
        "repair" => "Repairing SwitchTrade",
        "rollback" => "Rolling back SwitchTrade",
        "uninstall" => "Uninstalling SwitchTrade",
        _ => "Running SwitchTrade Setup",
    };

    private static async Task<string> ReadLinesAsync(StreamReader reader, Action<string>? onLine = null)
    {
        var content = new StringBuilder();
        while (await reader.ReadLineAsync() is { } line)
        {
            content.AppendLine(line);
            onLine?.Invoke(line);
        }
        return content.ToString();
    }

    private static string? ParseProgressStage(string line)
    {
        const string prefix = "SWITCHTRADE_SETUP_PROGRESS: ";
        if (!line.StartsWith(prefix, StringComparison.Ordinal)) return null;
        var stage = line[prefix.Length..].Trim();
        return stage.Length is > 0 and <= 64 &&
               stage.All(character => char.IsAsciiLetterOrDigit(character) || character == '_')
            ? stage
            : null;
    }

    private static string StageDescription(string stage) => stage switch
    {
        "package_integrity" => "Verifying the setup package...",
        "mutex" => "Preparing a safe installation transaction...",
        "transaction_recovery" => "Recovering an interrupted setup...",
        "prerequisites_enable" => "Enabling Windows Subsystem for Linux...",
        "wsl_update" => "Installing or updating Microsoft WSL...",
        "usbipd_install" => "Installing USB adapter support...",
        "host_capabilities" => "Checking Windows and WSL requirements...",
        "usb_identity" => "Locating the selected USB adapter...",
        "installed_integrity" => "Checking the current SwitchTrade installation...",
        "windows_stage" => "Staging the SwitchTrade desktop application...",
        "distro_identity" => "Preparing the isolated SwitchTrade environment...",
        "wsl_stage" => "Installing the SwitchTrade backend...",
        "wsl_validate" => "Validating the SwitchTrade backend...",
        "control_readiness" => "Checking the local SwitchTrade service...",
        "kernel_apply" => "Installing the SwitchTrade kernel...",
        "kernel_modules" => "Installing Wi-Fi kernel modules...",
        "kernel_verify" => "Validating the kernel and Wi-Fi driver...",
        "commit" => "Committing the installation...",
        "hardware_ownership" => "Preparing USB adapter ownership...",
        "hardware_readiness" => "Checking the selected Wi-Fi adapter...",
        "hardware_selection_import" => "Saving the Wi-Fi adapter selection...",
        "compensate" => "Restoring the previous working state...",
        "rollback_validate" => "Validating rollback files...",
        "rollback_commit" => "Restoring the previous SwitchTrade version...",
        _ => "Finishing SwitchTrade setup...",
    };
}
