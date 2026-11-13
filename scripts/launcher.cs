using System;
using System.Diagnostics;
using System.IO;

static class Program
{
    static int Main()
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\', '/');
        string script = Path.Combine(root, "scripts", "bootstrap.ps1");
        if (!File.Exists(script))
        {
            Console.Error.WriteLine("No esta scripts\\bootstrap.ps1 junto al ejecutable.");
            Pause();
            return 1;
        }

        var start = new ProcessStartInfo();
        start.FileName = "powershell.exe";
        start.Arguments = "-NoProfile -ExecutionPolicy Bypass -File \"" + script + "\" -RepoRoot \"" + root + "\"";
        start.WorkingDirectory = root;
        start.UseShellExecute = false;

        using (var process = Process.Start(start))
        {
            process.WaitForExit();
            if (process.ExitCode != 0)
            {
                Console.WriteLine();
                Console.WriteLine("No se ha podido arrancar Bass Tab.");
                Pause();
            }
            return process.ExitCode;
        }
    }

    static void Pause()
    {
        Console.WriteLine("Pulsa Enter para cerrar.");
        Console.ReadLine();
    }
}
