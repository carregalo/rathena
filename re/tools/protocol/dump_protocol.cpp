// Prints, as JSON, the map server's protocol for this build's PACKETVER:
//  - "packets": every entry of the packet table (clif_packetdb.hpp + clif_shuffle.hpp), with its length (-1 =
//    variable: a uint16 length at offset 2) and, for packets the server reads, the handler and the offsets of
//    the fields it reads;
//  - "structs": size and field offsets of the map packets used by the walking test.
// Output: re/spec/protocol/map.json (see build.bat).
#include <common/cbasetypes.hpp>
#include <common/mmo.hpp>
#include <map/packets.hpp>

#include "dump_common.hpp"

static bool first_packet = true;

static void packet_entry(int cmd, int length, const char* handler, const char* positions){
	std::printf("%s\n    {\"id\": \"0x%04x\", \"length\": %d, \"handler\": \"%s\", \"positions\": \"%s\"}",
		first_packet ? "" : ",", cmd & 0xFFFF, (int16)length, handler, positions);
	first_packet = false;
}

// The packet table is a list of packet()/parseable_packet() lines; here each line prints itself instead of
// filling the server's table. The handler is only stringified, so no server function is needed.
#define packetdb_addpacket(cmd, length, func, ...) packet_entry((cmd), (int)(length), #func, #__VA_ARGS__)

static void dump_packets(){
#include <map/clif_packetdb.hpp>
#include <map/clif_shuffle.hpp>
}

int main(){
	std::printf("{\n  \"packetver\": %d,\n  \"packets\": [", PACKETVER);
	dump_packets();
	std::printf("\n  ],\n  \"structs\": {");

	STRUCT_BEGIN(PACKET_ZC_ACCEPT_ENTER); FIELD(PACKET_ZC_ACCEPT_ENTER, startTime); FIELD(PACKET_ZC_ACCEPT_ENTER, posDir);
	FIELD(PACKET_ZC_ACCEPT_ENTER, xSize); FIELD(PACKET_ZC_ACCEPT_ENTER, ySize); STRUCT_END();
	STRUCT_BEGIN(PACKET_ZC_NOTIFY_PLAYERMOVE); FIELD(PACKET_ZC_NOTIFY_PLAYERMOVE, moveStartTime);
	FIELD(PACKET_ZC_NOTIFY_PLAYERMOVE, moveData); STRUCT_END();
	STRUCT_BEGIN(PACKET_ZC_STOPMOVE); FIELD(PACKET_ZC_STOPMOVE, AID); FIELD(PACKET_ZC_STOPMOVE, xPos);
	FIELD(PACKET_ZC_STOPMOVE, yPos); STRUCT_END();
	STRUCT_BEGIN(PACKET_ZC_NOTIFY_TIME); FIELD(PACKET_ZC_NOTIFY_TIME, time); STRUCT_END();

	std::printf("\n  }\n}\n");
	return 0;
}
