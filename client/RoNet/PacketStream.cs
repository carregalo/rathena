using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;

namespace RoNet
{
    /// <summary>
    /// A TCP connection that reads whole packets: the server writes packets back to back, and each one's length
    /// comes from the packet length table (fixed) or from the uint16 at offset 2 (variable, -1 in the table).
    /// See re/spec/protocol/README.md.
    /// </summary>
    public sealed class PacketStream : IDisposable
    {
        private readonly TcpClient tcp;
        private readonly NetworkStream net;
        private readonly Dictionary<ushort, short> lengths;
        private readonly SemaphoreSlim writeLock = new SemaphoreSlim(1, 1);

        private PacketStream(TcpClient tcp, Dictionary<ushort, short> lengths)
        {
            this.tcp = tcp;
            net = tcp.GetStream();
            this.lengths = lengths;
        }

        public static async Task<PacketStream> ConnectAsync(string host, int port, Dictionary<ushort, short> lengths)
        {
            var tcp = new TcpClient { NoDelay = true };
            await tcp.ConnectAsync(host, port).ConfigureAwait(false);
            return new PacketStream(tcp, lengths);
        }

        /// <summary>Reads exactly count bytes (for the raw account id the char server sends first).</summary>
        public async Task<byte[]> ReadRawAsync(int count, CancellationToken ct = default)
        {
            var buf = new byte[count];
            int read = 0;
            while (read < count)
            {
                int n = await net.ReadAsync(buf, read, count - read, ct).ConfigureAwait(false);
                if (n == 0)
                    throw new IOException("connection closed by the server");
                read += n;
            }
            return buf;
        }

        /// <summary>Reads the next packet, id included.</summary>
        public async Task<byte[]> ReadPacketAsync(CancellationToken ct = default)
        {
            byte[] head = await ReadRawAsync(2, ct).ConfigureAwait(false);
            ushort id = BitConverter.ToUInt16(head, 0);
            if (!lengths.TryGetValue(id, out short length))
                throw new InvalidDataException($"unknown packet 0x{id:x4}: its length is not in the table, the stream cannot be split");
            if (length == -1)
            {
                byte[] size = await ReadRawAsync(2, ct).ConfigureAwait(false);
                length = (short)BitConverter.ToUInt16(size, 0);
                byte[] rest = await ReadRawAsync(length - 4, ct).ConfigureAwait(false);
                return Concat(head, size, rest);
            }
            return Concat(head, await ReadRawAsync(length - 2, ct).ConfigureAwait(false));
        }

        public async Task SendAsync(byte[] packet, CancellationToken ct = default)
        {
            await writeLock.WaitAsync(ct).ConfigureAwait(false);
            try
            {
                await net.WriteAsync(packet, 0, packet.Length, ct).ConfigureAwait(false);
            }
            finally
            {
                writeLock.Release();
            }
        }

        public void Dispose()
        {
            net.Dispose();
            tcp.Dispose();
        }

        private static byte[] Concat(params byte[][] parts)
        {
            int total = 0;
            foreach (var p in parts)
                total += p.Length;
            var all = new byte[total];
            int off = 0;
            foreach (var p in parts)
            {
                Buffer.BlockCopy(p, 0, all, off, p.Length);
                off += p.Length;
            }
            return all;
        }
    }
}
