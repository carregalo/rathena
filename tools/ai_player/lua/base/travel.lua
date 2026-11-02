-- Viaja ate outro mapa (ou um ponto dele) a pe, atravessando os portais pelo caminho mais curto.
-- args: map = mapa de destino; x, y = ponto no destino (opcional)
local route, route_map, started, map_since = nil, nil, nil, nil

function Tick(args)
	started = started or GetTick()
	local here = GetMap()
	local x, y = GetV(V_POSITION, MyID)
	if here == args.map and (not args.x or math.max(math.abs(x - args.x), math.abs(y - args.y)) <= 2) then
		Done("cheguei em " .. here .. " " .. x .. "," .. y)
		return
	end
	if route == nil or route_map ~= here then  -- comeco, ou acabei de passar por um portal
		local err
		route, err = Route(args.map, args.x, args.y)
		route_map, map_since = here, GetTick()
		if not route then
			Done("nao achei caminho ate " .. tostring(args.map) .. ": " .. tostring(err))
			return
		end
	end
	if GetTick() - map_since > 180000 then  -- 3 minutos no mesmo mapa: algo bloqueia o caminho
		Done("fiquei presa em " .. here .. " " .. x .. "," .. y .. " tentando chegar a " .. tostring(args.map))
		return
	end
	local step = route[1]
	Move(step.x, step.y, step.span or 0)
end
