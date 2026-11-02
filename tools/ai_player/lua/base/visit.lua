-- Vai ate um NPC, em qualquer mapa, e conversa com ele; termina quando ele responde.
-- args: npc = nome do NPC (ou parte dele); map = mapa, para escolher entre NPCs de mesmo nome (opcional)
local target, talked_at = nil, nil

local function choose(args)
	-- o mais perto que da para alcancar a pe (alguns ficam em salas fechadas)
	for _, n in ipairs(FindNpc(args.npc or "")) do
		if (not args.map or n.map == args.map) and Route(n.map, n.x, n.y) then return n end
	end
	return nil
end

function Tick(args)
	if not target then
		target = choose(args)
		if not target then
			Done("nao achei um caminho ate um NPC chamado " .. tostring(args.npc))
			return
		end
	end
	if GetNpcWait() then
		Done("estou falando com " .. target.name .. " em " .. target.map)
	elseif talked_at then
		if GetTick() - talked_at > 5000 then
			Done("falei com " .. target.name .. " em " .. target.map .. " " .. target.x .. "," .. target.y)
		end
	else
		local arrived, err = FollowRoute(target.map, target.x, target.y, 6)
		if arrived then
			Talk(target.name, target.x, target.y)  -- o corpo chega perto e clica
			talked_at = GetTick()
		elseif arrived == nil then
			Done("nao consegui chegar ate " .. target.name .. " em " .. target.map .. ": " .. tostring(err))
		end
	end
end
