// Prints the map-server packet table exactly as packetdb_readdb() builds it for this build's PACKETVER:
// "<id> <length> <handler>" per line (length -1 = variable, handler "nullptr" = not parsed by the server).
#include <cstdio>

#include "common/cbasetypes.hpp"
#include "common/mmo.hpp"
#include "map/packets.hpp"

#define packetdb_addpacket(cmd, len, func, ...) \
	std::printf("0x%04x %d %s %s\n", (unsigned)(uint16)(cmd), (int)(int16)(len), #func, #__VA_ARGS__)

static void dump(){
#include "map/clif_packetdb.hpp"
#include "map/clif_shuffle.hpp"
}

int main(){
	std::printf("# PACKETVER %d\n", PACKETVER);
#ifdef PACKET_OBFUSCATION
	std::printf("# obfuscation 1\n");
#endif
	dump();
	return 0;
}
