using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using RoNet;

// Usage: RoNet.Console [host]. The account comes from tests/local.env (WALKTEST_USER, WALKTEST_PASS).
// Walks to a few cells around the start position and fails if the server does not acknowledge each walk.
class Program
{
    static async Task<int> Main(string[] args)
    {
        string host = args.Length > 0 ? args[0] : "127.0.0.1";
        var env = ReadEnv();
        using var client = new GameClient();
        await client.ConnectAsync(host, env["WALKTEST_USER"], env["WALKTEST_PASS"], "Bilbo");

        var entered = (EnteredMap)await NextAsync(client, 3000);
        Console.WriteLine($"{client.CharName} entered {entered.Map} at {entered.X},{entered.Y} (speed {client.Speed})");

        int x = entered.X, y = entered.Y;
        foreach (var (dx, dy) in new[] { (5, 0), (0, 5), (-5, -5) })
        {
            await client.WalkAsync(x + dx, y + dy);
            if (!(await NextAsync(client, 2000) is StartedWalking w))
                return Fail("walk not acknowledged");
            Console.WriteLine($"walking {w.X0},{w.Y0} -> {w.X1},{w.Y1}");
            if (w.X1 != x + dx || w.Y1 != y + dy)
                return Fail("server sent another destination");
            x = w.X1; y = w.Y1;
            await Task.Delay(1500);   // let the walk finish (5 cells x 150 ms, diagonals 1.4x)
        }
        Console.WriteLine("OK");
        return 0;
    }

    static async Task<GameEvent> NextAsync(GameClient c, int timeoutMs)
    {
        for (int waited = 0; waited < timeoutMs; waited += 20)
        {
            if (c.Events.TryDequeue(out var e))
                return e is Disconnected d ? throw new IOException(d.Reason) : e;
            await Task.Delay(20);
        }
        throw new TimeoutException("no answer from the server");
    }

    static int Fail(string why)
    {
        Console.WriteLine("FAIL: " + why);
        return 1;
    }

    static System.Collections.Generic.Dictionary<string, string> ReadEnv()
    {
        string dir = AppContext.BaseDirectory;
        while (dir != null && !File.Exists(Path.Combine(dir, "tests", "local.env")))
            dir = Path.GetDirectoryName(dir);
        if (dir == null)
            throw new FileNotFoundException("tests/local.env not found");
        return File.ReadAllLines(Path.Combine(dir, "tests", "local.env"))
            .Where(l => l.Contains('=') && !l.TrimStart().StartsWith("#"))
            .Select(l => l.Split('=', 2))
            .ToDictionary(p => p[0].Trim(), p => p[1].Trim());
    }
}
