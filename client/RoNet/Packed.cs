using System;
using System.Text;

namespace RoNet
{
    /// <summary>
    /// Field helpers: little-endian numbers, fixed-size strings, and the packed positions the server writes with
    /// WBUFPOS (x, y, direction in 3 bytes) and WBUFPOS2 (two positions in 6 bytes).
    /// </summary>
    public static class Packed
    {
        public static ushort U16(byte[] p, int at) => BitConverter.ToUInt16(p, at);
        public static uint U32(byte[] p, int at) => BitConverter.ToUInt32(p, at);

        public static string Text(byte[] p, int at, int size)
        {
            int end = at;
            while (end < at + size && p[end] != 0)
                end++;
            return Encoding.ASCII.GetString(p, at, end - at);
        }

        public static void PutU16(byte[] p, int at, int v) => BitConverter.GetBytes((ushort)v).CopyTo(p, at);
        public static void PutU32(byte[] p, int at, uint v) => BitConverter.GetBytes(v).CopyTo(p, at);

        public static void PutText(byte[] p, int at, int size, string s)
        {
            byte[] b = Encoding.ASCII.GetBytes(s);
            Buffer.BlockCopy(b, 0, p, at, Math.Min(b.Length, size - 1));
        }

        /// <summary>A new packet buffer with its id already written.</summary>
        public static byte[] Packet(int id, int length)
        {
            var p = new byte[length];
            PutU16(p, 0, id);
            return p;
        }

        public static (int x, int y, int dir) Pos(byte[] p, int at)
        {
            int x = (p[at] << 2) | (p[at + 1] >> 6);
            int y = ((p[at + 1] & 0x3f) << 4) | (p[at + 2] >> 4);
            return (x, y, p[at + 2] & 0x0f);
        }

        public static (int x0, int y0, int x1, int y1) Move(byte[] p, int at)
        {
            int x0 = (p[at] << 2) | (p[at + 1] >> 6);
            int y0 = ((p[at + 1] & 0x3f) << 4) | (p[at + 2] >> 4);
            int x1 = ((p[at + 2] & 0x0f) << 6) | (p[at + 3] >> 2);
            int y1 = ((p[at + 3] & 0x03) << 8) | p[at + 4];
            return (x0, y0, x1, y1);
        }

        public static void PutPos(byte[] p, int at, int x, int y, int dir = 0)
        {
            p[at] = (byte)(x >> 2);
            p[at + 1] = (byte)((x << 6) | ((y >> 4) & 0x3f));
            p[at + 2] = (byte)((y << 4) | (dir & 0x0f));
        }
    }
}
