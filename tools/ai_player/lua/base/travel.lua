-- Viaja ate outro mapa (ou um ponto dele) a pe, atravessando os portais pelo caminho mais curto.
-- args: map = mapa de destino; x, y = ponto no destino (opcional)
local last_map, map_since = nil, nil

function Tick(args)
	local here = GetMap()
	if here ~= last_map then last_map, map_since = here, GetTick() end
	local arrived, err = FollowRoute(args.map, args.x, args.y)
	local x, y = GetV(V_POSITION, MyID)
	if arrived then
		Done("cheguei em " .. here .. " " .. x .. "," .. y)
	elseif arrived == nil then
		Done("nao achei caminho ate " .. tostring(args.map) .. ": " .. tostring(err))
	elseif GetTick() - map_since > 180000 then  -- 3 minutos no mesmo mapa: algo bloqueia o caminho
		Done("fiquei presa em " .. here .. " " .. x .. "," .. y .. " tentando chegar a " .. tostring(args.map))
	end
end
