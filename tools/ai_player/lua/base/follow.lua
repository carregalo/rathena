-- Segue um jogador de perto, como uma companheira; termina se ele sumir de vista por 15 segundos.
-- args: player = nome do jogador; distance = distancia a manter (opcional, 2)
local lost_since = nil

function Tick(args)
	local keep = args.distance or 2
	local id = FindByName("player", args.player or "")
	if id == 0 then
		lost_since = lost_since or GetTick()
		if GetTick() - lost_since > 15000 then
			Done("perdi " .. tostring(args.player) .. " de vista")
			return
		end
		local x, y = GetLastSeen(args.player or "")
		if x then Move(x, y) end  -- vai ate onde ele foi visto por ultimo
		return
	end
	lost_since = nil
	if GetDistance(id) > keep then
		local x, y = GetV(V_POSITION, id)
		Move(x, y)
	end
end
