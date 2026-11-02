using System;
using System.Collections.Concurrent;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Threading;
using System.Threading.Tasks;

namespace RoNet
{
    /// <summary>Something that happened in the game, for the game loop to apply (Unity reads them each frame).</summary>
    public abstract class GameEvent { }

    /// <summary>The character is on a map, standing at (X, Y).</summary>
    public sealed class EnteredMap : GameEvent
    {
        public string Map; public int X, Y;
    }

    /// <summary>The server accepted a walk: from (X0, Y0) to (X1, Y1); Speed is milliseconds per straight cell.</summary>
    public sealed class StartedWalking : GameEvent
    {
        public int X0, Y0, X1, Y1, Speed;
    }

    /// <summary>The character stopped at (X, Y) before reaching its destination.</summary>
    public sealed class Stopped : GameEvent
    {
        public int X, Y;
    }

    /// <summary>The connection ended or failed.</summary>
    public sealed class Disconnected : GameEvent
    {
        public string Reason;
    }

    /// <summary>
    /// Logs in, picks (or creates) the account's character, enters its map and walks, following
    /// re/spec/protocol/README.md. Every offset used here comes from the generated files in re/spec/protocol.
    /// </summary>
    public sealed class GameClient : IDisposable
    {
        public const uint PacketVer = 20211103;
        private const int LoginPort = 6900;
        private const int CharacterInfoSize = 175;   // CHARACTER_INFO
        private const int KeepAliveMs = 10000;       // the official client sends CZ_REQUEST_TIME every ~12 s

        public ConcurrentQueue<GameEvent> Events { get; } = new ConcurrentQueue<GameEvent>();
        public uint AccountId { get; private set; }
        public uint CharId { get; private set; }
        public string CharName { get; private set; }
        public string MapName { get; private set; }
        public int Speed { get; private set; } = 150;

        private readonly Stopwatch clock = Stopwatch.StartNew();
        private readonly CancellationTokenSource stop = new CancellationTokenSource();
        private PacketStream map;
        private uint loginId1, loginId2;
        private byte sex;

        private uint Tick => (uint)clock.ElapsedMilliseconds;

        /// <summary>Login, character server and map entry. Returns once the character is on its map.</summary>
        public async Task ConnectAsync(string host, string user, string password, string newCharName)
        {
            (string charHost, int charPort) = await LoginAsync(host, user, password).ConfigureAwait(false);
            (string mapHost, int mapPort, string mapName) =
                await SelectCharacterAsync(charHost, charPort, newCharName).ConfigureAwait(false);
            await EnterMapAsync(mapHost, mapPort, mapName).ConfigureAwait(false);
            _ = Task.Run(() => MapLoopAsync(stop.Token));
            _ = Task.Run(() => KeepAliveAsync(stop.Token));
        }

        /// <summary>Asks the server to walk to (x, y); it answers with StartedWalking, or nothing if no path.</summary>
        public Task WalkAsync(int x, int y)
        {
            byte[] p = Packed.Packet(0x035f, 5);   // CZ_REQUEST_MOVE: destination @2
            Packed.PutPos(p, 2, x, y);
            return map.SendAsync(p);
        }

        public void Dispose()
        {
            stop.Cancel();
            map?.Dispose();
        }

        // ------------------------------------------------------------------ login server

        private async Task<(string, int)> LoginAsync(string host, string user, string password)
        {
            using (var s = await PacketStream.ConnectAsync(host, LoginPort, PacketLengths.LoginChar).ConfigureAwait(false))
            {
                byte[] p = Packed.Packet(0x0064, 55);   // CA_LOGIN
                Packed.PutU32(p, 2, PacketVer);
                Packed.PutText(p, 6, 24, user);
                Packed.PutText(p, 30, 24, password);
                await s.SendAsync(p).ConfigureAwait(false);

                byte[] r = await s.ReadPacketAsync().ConfigureAwait(false);
                ushort id = Packed.U16(r, 0);
                if (id == 0x083e)
                    throw new IOException($"login refused (error {Packed.U32(r, 2)})");
                if (id != 0x0ac4)
                    throw new IOException($"unexpected login answer 0x{id:x4}");
                loginId1 = Packed.U32(r, 4);
                AccountId = Packed.U32(r, 8);
                loginId2 = Packed.U32(r, 12);
                sex = r[46];
                if (r.Length < 64 + 160)
                    throw new IOException("the login server lists no character server");
                return (new IPAddress(new[] { r[64], r[65], r[66], r[67] }).ToString(), Packed.U16(r, 68));
            }
        }

        // ------------------------------------------------------------------ character server

        private async Task<(string, int, string)> SelectCharacterAsync(string host, int port, string newCharName)
        {
            using (var s = await PacketStream.ConnectAsync(host, port, PacketLengths.LoginChar).ConfigureAwait(false))
            {
                byte[] p = Packed.Packet(0x0065, 17);   // CH_ENTER
                Packed.PutU32(p, 2, AccountId);
                Packed.PutU32(p, 6, loginId1);
                Packed.PutU32(p, 10, loginId2);
                p[16] = sex;
                await s.SendAsync(p).ConfigureAwait(false);
                await s.ReadRawAsync(4).ConfigureAwait(false);   // the account id, without a packet id

                int slot = -1;
                while (slot < 0)
                {
                    byte[] r = await s.ReadPacketAsync().ConfigureAwait(false);
                    switch (Packed.U16(r, 0))
                    {
                        case 0x006b:   // HC_ACCEPT_ENTER: every character of the account, from @27
                            if (r.Length >= 27 + CharacterInfoSize)
                                slot = ReadCharacter(r, 27);
                            else
                                slot = await CreateCharacterAsync(s, newCharName).ConfigureAwait(false);
                            break;
                        case 0x006c:
                            throw new IOException($"character server refused the account (error {r[2]})");
                    }
                }

                byte[] select = Packed.Packet(0x0066, 3);   // CH_SELECT_CHAR
                select[2] = (byte)slot;
                await s.SendAsync(select).ConfigureAwait(false);
                while (true)
                {
                    byte[] r = await s.ReadPacketAsync().ConfigureAwait(false);
                    ushort id = Packed.U16(r, 0);
                    if (id == 0x0ac5)   // HC_NOTIFY_ZONESVR
                    {
                        CharId = Packed.U32(r, 2);
                        string mapName = Packed.Text(r, 6, 16);
                        string ip = new IPAddress(new[] { r[22], r[23], r[24], r[25] }).ToString();
                        return (ip, Packed.U16(r, 26), mapName);
                    }
                    if (id == 0x006c)
                        throw new IOException($"character selection refused (error {r[2]})");
                }
            }
        }

        private int ReadCharacter(byte[] r, int at)
        {
            CharId = Packed.U32(r, at);
            Speed = Packed.U16(r, at + 82);
            CharName = Packed.Text(r, at + 108, 24);
            return r[at + 138];   // slot (CharNum)
        }

        private async Task<int> CreateCharacterAsync(PacketStream s, string name)
        {
            byte[] p = Packed.Packet(0x0a39, 36);   // CH_MAKE_CHAR: one fixed look, no choices
            Packed.PutText(p, 2, 24, name);
            p[26] = 0;                              // slot
            Packed.PutU16(p, 27, 0);                // hair colour
            Packed.PutU16(p, 29, 1);                // hair style
            Packed.PutU32(p, 31, 0);                // class
            p[35] = sex;
            await s.SendAsync(p).ConfigureAwait(false);
            while (true)
            {
                byte[] r = await s.ReadPacketAsync().ConfigureAwait(false);
                ushort id = Packed.U16(r, 0);
                if (id == 0x0b6f)   // HC_ACCEPT_MAKECHAR: the new character @2
                    return ReadCharacter(r, 2);
                if (id == 0x006e)
                    throw new IOException($"character creation refused (error {r[2]})");
            }
        }

        // ------------------------------------------------------------------ map server

        private async Task EnterMapAsync(string host, int port, string mapName)
        {
            map = await PacketStream.ConnectAsync(host, port, PacketLengths.Map).ConfigureAwait(false);
            byte[] p = Packed.Packet(0x0436, 23);   // CZ_ENTER
            Packed.PutU32(p, 2, AccountId);
            Packed.PutU32(p, 6, CharId);
            Packed.PutU32(p, 10, loginId1);
            Packed.PutU32(p, 14, Tick);
            p[22] = sex;
            await map.SendAsync(p).ConfigureAwait(false);
            while (true)
            {
                byte[] r = await map.ReadPacketAsync().ConfigureAwait(false);
                ushort id = Packed.U16(r, 0);
                if (id == 0x02eb)   // ZC_ACCEPT_ENTER: position @6
                {
                    (int x, int y, _) = Packed.Pos(r, 6);
                    MapName = mapName.Replace(".gat", "");
                    Events.Enqueue(new EnteredMap { Map = MapName, X = x, Y = y });
                    break;
                }
                if (id == 0x0074)
                    throw new IOException($"map server refused entry (error {r[2]})");
            }
            await map.SendAsync(Packed.Packet(0x007d, 2)).ConfigureAwait(false);   // CZ_NOTIFY_ACTORINIT
        }

        private async Task MapLoopAsync(CancellationToken ct)
        {
            try
            {
                while (!ct.IsCancellationRequested)
                {
                    byte[] r = await map.ReadPacketAsync(ct).ConfigureAwait(false);
                    switch (Packed.U16(r, 0))
                    {
                        case 0x0087:   // ZC_NOTIFY_PLAYERMOVE: our walk was accepted, origin and destination @6
                            (int x0, int y0, int x1, int y1) = Packed.Move(r, 6);
                            Events.Enqueue(new StartedWalking { X0 = x0, Y0 = y0, X1 = x1, Y1 = y1, Speed = Speed });
                            break;
                        case 0x0088:   // ZC_STOPMOVE: unit @2, x @6, y @8
                            if (Packed.U32(r, 2) == AccountId)
                                Events.Enqueue(new Stopped { X = Packed.U16(r, 6), Y = Packed.U16(r, 8) });
                            break;
                    }
                }
            }
            catch (Exception e) when (!(e is OperationCanceledException))
            {
                Events.Enqueue(new Disconnected { Reason = e.Message });
            }
        }

        private async Task KeepAliveAsync(CancellationToken ct)
        {
            try
            {
                while (!ct.IsCancellationRequested)
                {
                    await Task.Delay(KeepAliveMs, ct).ConfigureAwait(false);
                    byte[] p = Packed.Packet(0x0360, 6);   // CZ_REQUEST_TIME: client time @2
                    Packed.PutU32(p, 2, Tick);
                    await map.SendAsync(p, ct).ConfigureAwait(false);
                }
            }
            catch (OperationCanceledException)
            {
            }
        }
    }
}
