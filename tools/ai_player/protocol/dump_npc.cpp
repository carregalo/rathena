// Prints the layouts of the NPC dialog, input and shop packets for this build's PACKETVER, so roclient.py
// parses them exactly (offsetof on the server's own structs).
#include <cstddef>
#include <cstdio>

#include "common/cbasetypes.hpp"
#include "common/mmo.hpp"
#include "map/packets.hpp"

#define F(s, f) std::printf("%s.%s %d\n", #s, #f, (int)offsetof(struct s, f))
#define S(s) std::printf("%s size %d\n", #s, (int)sizeof(struct s))

int main(){
	std::printf("# PACKETVER %d buylist 0x%04x\n", PACKETVER, HEADER_ZC_PC_PURCHASE_ITEMLIST);
	S(PACKET_ZC_PC_PURCHASE_ITEMLIST); F(PACKET_ZC_PC_PURCHASE_ITEMLIST, items);
	S(PACKET_ZC_PC_PURCHASE_ITEMLIST_sub); F(PACKET_ZC_PC_PURCHASE_ITEMLIST_sub, price); F(PACKET_ZC_PC_PURCHASE_ITEMLIST_sub, discountPrice);
	F(PACKET_ZC_PC_PURCHASE_ITEMLIST_sub, itemType); F(PACKET_ZC_PC_PURCHASE_ITEMLIST_sub, itemId);
	S(PACKET_CZ_PC_PURCHASE_ITEMLIST); F(PACKET_CZ_PC_PURCHASE_ITEMLIST, items);
	S(PACKET_CZ_PC_PURCHASE_ITEMLIST_sub); F(PACKET_CZ_PC_PURCHASE_ITEMLIST_sub, amount); F(PACKET_CZ_PC_PURCHASE_ITEMLIST_sub, itemId);
	S(PACKET_ZC_PC_SELL_ITEMLIST); F(PACKET_ZC_PC_SELL_ITEMLIST, items);
	S(PACKET_ZC_PC_SELL_ITEMLIST_sub); F(PACKET_ZC_PC_SELL_ITEMLIST_sub, index); F(PACKET_ZC_PC_SELL_ITEMLIST_sub, price); F(PACKET_ZC_PC_SELL_ITEMLIST_sub, overcharge);
	S(PACKET_CZ_PC_SELL_ITEMLIST); F(PACKET_CZ_PC_SELL_ITEMLIST, sellList);
	S(PACKET_CZ_PC_SELL_ITEMLIST_sub); F(PACKET_CZ_PC_SELL_ITEMLIST_sub, index); F(PACKET_CZ_PC_SELL_ITEMLIST_sub, amount);
	S(PACKET_ZC_SELECT_DEALTYPE); S(PACKET_CZ_ACK_SELECT_DEALTYPE); F(PACKET_CZ_ACK_SELECT_DEALTYPE, GID); F(PACKET_CZ_ACK_SELECT_DEALTYPE, type);
	S(PACKET_ZC_PC_PURCHASE_RESULT); S(PACKET_ZC_MENU_LIST); F(PACKET_ZC_MENU_LIST, npcId); F(PACKET_ZC_MENU_LIST, menu);
	S(PACKET_ZC_OPEN_EDITDLG); S(PACKET_ZC_OPEN_EDITDLGSTR);
	S(PACKET_CZ_INPUT_EDITDLG); F(PACKET_CZ_INPUT_EDITDLG, GID); F(PACKET_CZ_INPUT_EDITDLG, value);
	S(PACKET_CZ_INPUT_EDITDLGSTR); F(PACKET_CZ_INPUT_EDITDLGSTR, GID); F(PACKET_CZ_INPUT_EDITDLGSTR, value);
	return 0;
}
