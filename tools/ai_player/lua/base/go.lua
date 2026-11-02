-- Vai ate um ponto do mapa, contornando obstaculos; termina ao chegar ou apos 60 segundos.
-- args: x, y
local started = nil

function Tick(args)
	started = started or GetTick()
	local x, y = GetV(V_POSITION, MyID)
	if x == args.x and y == args.y then
		Done("cheguei em " .. x .. "," .. y)
		return
	end
	if GetTick() - started > 60000 then
		Done("nao consegui chegar em " .. tostring(args.x) .. "," .. tostring(args.y) .. "; parei em " .. x .. "," .. y)
		return
	end
	Move(args.x, args.y)
end
