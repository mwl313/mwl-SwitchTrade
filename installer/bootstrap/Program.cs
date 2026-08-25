using System.Diagnostics;
using System.Windows.Forms;

namespace SwitchTrade.Setup;

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        var action = args.FirstOrDefault(value =>
            value is "audit" or "install" or "repair" or "update" or "rollback" or "uninstall") ?? "audit";
        var script = Path.Combine(AppContext.BaseDirectory, "installer", "SwitchTradeSetup.ps1");
        if (!File.Exists(script))
        {
            MessageBox.Show("The SwitchTrade setup payload is incomplete.", "SwitchTrade Setup",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 2;
        }

        var start = new ProcessStartInfo("powershell.exe")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-NonInteractive");
        start.ArgumentList.Add("-ExecutionPolicy");
        start.ArgumentList.Add("Bypass");
        start.ArgumentList.Add("-File");
        start.ArgumentList.Add(script);
        start.ArgumentList.Add("-Action");
        start.ArgumentList.Add(char.ToUpperInvariant(action[0]) + action[1..]);
        foreach (var option in args)
        {
            if (option == "--purge-distro") start.ArgumentList.Add("-PurgeDistro");
            if (option == "--accept-global-kernel-change") start.ArgumentList.Add("-AcceptGlobalKernelChange");
            if (option == "--accept-prerequisite-changes") start.ArgumentList.Add("-AcceptPrerequisiteChanges");
            if (option == "--accept-vmware-release") start.ArgumentList.Add("-AcceptVmwareRelease");
            if (option == "--no-shortcut") start.ArgumentList.Add("-NoShortcut");
        }

        try
        {
            using var process = Process.Start(start) ?? throw new InvalidOperationException("Setup did not start.");
            var outputTask = process.StandardOutput.ReadToEndAsync();
            var errorTask = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            Task.WaitAll(outputTask, errorTask);
            var success = process.ExitCode == 0;
            var message = success ? outputTask.Result.Trim() : errorTask.Result.Trim();
            if (string.IsNullOrWhiteSpace(message))
                message = success ? "SwitchTrade setup completed." : "SwitchTrade setup did not complete.";
            MessageBox.Show(message, "SwitchTrade Setup", MessageBoxButtons.OK,
                success ? MessageBoxIcon.Information : MessageBoxIcon.Error);
            return process.ExitCode;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "SwitchTrade Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
