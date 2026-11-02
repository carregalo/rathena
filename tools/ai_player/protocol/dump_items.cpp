// Prints the field offsets of the inventory packets for this build's PACKETVER, so roclient.py parses them exactly.
#include <cstddef>
#include <cstdio>

#include "common/cbasetypes.hpp"
#include "common/mmo.hpp"
#include "map/packets.hpp"

#define F(s, f) std::printf("%s.%s %d\n", #s, #f, (int)offsetof(struct s, f))
#define S(s) std::printf("%s size %d\n", #s, (int)sizeof(struct s))

int main(){
	std::printf("# PACKETVER %d normal 0x%04x equip 0x%04x pickup 0x%04x\n", PACKETVER, inventorylistnormalType, inventorylistequipType, HEADER_ZC_ITEM_PICKUP_ACK);
	S(NORMALITEM_INFO); F(NORMALITEM_INFO, index); F(NORMALITEM_INFO, ITID); F(NORMALITEM_INFO, type); F(NORMALITEM_INFO, count); F(NORMALITEM_INFO, WearState);
	S(EQUIPITEM_INFO); F(EQUIPITEM_INFO, index); F(EQUIPITEM_INFO, ITID); F(EQUIPITEM_INFO, type); F(EQUIPITEM_INFO, location); F(EQUIPITEM_INFO, WearState); F(EQUIPITEM_INFO, RefiningLevel);
	F(packet_itemlist_normal, list); F(packet_itemlist_equip, list);
	S(PACKET_ZC_ITEM_PICKUP_ACK); F(PACKET_ZC_ITEM_PICKUP_ACK, Index); F(PACKET_ZC_ITEM_PICKUP_ACK, count); F(PACKET_ZC_ITEM_PICKUP_ACK, nameid); F(PACKET_ZC_ITEM_PICKUP_ACK, location); F(PACKET_ZC_ITEM_PICKUP_ACK, type); F(PACKET_ZC_ITEM_PICKUP_ACK, result);
	S(PACKET_ZC_USE_ITEM_ACK); F(PACKET_ZC_USE_ITEM_ACK, index); F(PACKET_ZC_USE_ITEM_ACK, amount); F(PACKET_ZC_USE_ITEM_ACK, result);
	std::printf("useItemAckType 0x%04x\n", useItemAckType);
	S(PACKET_ZC_REQ_WEAR_EQUIP_ACK); F(PACKET_ZC_REQ_WEAR_EQUIP_ACK, index); F(PACKET_ZC_REQ_WEAR_EQUIP_ACK, wearLocation); F(PACKET_ZC_REQ_WEAR_EQUIP_ACK, result);
	return 0;
}
