-- Vai ate um NPC, em qualquer mapa, e conversa com ele; termina quando ele responde.
-- args: npc = nome do NPC (ou parte dele); map = mapa, para escolher entre NPCs de mesmo nome (opcional)
local target, route, route_map, talked_at = nil, nil, nil, nil

local function choose(args)
	-- o mais perto que da para alcancar a pe (alguns ficam em salas fechadas)
	for _, n in ipairs(FindNpc(args.npc or "")) do
		if not args.map or n.map == args.map then
			local r = Route(n.map, n.x, n.y)
			if r then return n, r end
		end
	end
	return nil, nil
end

function Tick(args)
	local here = GetMap()
	if not target then
		target, route = choose(args)
		route_map = here
		if not target then
			Done("nao achei um caminho ate um NPC chamado " .. tostring(args.npc))
			return
		end
	end
	if GetNpcWait() then
		Done("estou falando com " .. target.name .. " em " .. target.map)
		return
	end
	if talked_at then
		if GetTick() - talked_at > 5000 then
			Done("falei com " .. target.name .. " em " .. target.map .. " " .. target.x .. "," .. target.y)
		end
		return
	end
	local x, y = GetV(V_POSITION, MyID)
	if here == target.map and math.max(math.abs(x - target.x), math.abs(y - target.y)) <= 6 then
		Talk(target.name, target.x, target.y)  -- o corpo chega perto e clica
		talked_at = GetTick()
		return
	end
	if route_map ~= here then  -- passei por um portal: recalcula dali
		local err
		route, err = Route(target.map, target.x, target.y)
		route_map = here
		if not route then
			Done("nao achei caminho ate " .. target.name .. " em " .. target.map .. ": " .. tostring(err))
			return
		end
	end
	local step = route[1]
	if not Move(step.x, step.y, step.span or 3) then
		Done("nao consegui andar ate " .. target.name .. " a partir de " .. here .. " " .. x .. "," .. y)
	end
end
