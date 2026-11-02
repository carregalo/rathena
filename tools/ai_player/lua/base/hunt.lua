-- Caca monstros de um tipo: persegue o mais proximo, ataca, pega o que cair e passa para o proximo.
-- args: monster = nome do monstro; limit = quantos derrotar antes de terminar (opcional); wander = false para nao sair procurando
local target, since, kills = 0, 0, 0
local skip, tries = {}, {}
local last_found, loot_until = 0, 0

local function nearest_item()
	local best
	for _, item in ipairs(GetGroundItems()) do
		if item.dist <= 6 and (tries[item.id] or 0) < 6 and (not best or item.dist < best.dist) then
			best = item
		end
	end
	return best
end

local function nearest_monster(name)
	local best, best_dist = 0, math.huge
	for _, id in ipairs(GetActors()) do
		if IsMonster(id) == 1 and not skip[id] and string.lower(GetV(V_NAME, id)) == name then
			local d = GetDistance(id)
			if d < best_dist then best, best_dist = id, d end
		end
	end
	return best
end

function Start(args)
	last_found = GetTick()
end

function Tick(args)
	local name = string.lower(args.monster or "")
	if target ~= 0 then
		if GetV(V_TYPE, target) == nil then  -- morreu ou saiu de vista
			if WasKilled(target) then
				kills = kills + 1
				loot_until = GetTick() + 1500  -- o que ele deixa cair aparece logo depois
			end
			target = 0
		elseif GetTick() - since > 15000 then  -- 15 s sem conseguir bater: inalcancavel
			skip[target] = true
			target = 0
		else
			if Attack(target) == 2 then since = GetTick() end  -- CHASE -> ATTACK, como a IA do jogo
			return
		end
	end

	local item = nearest_item()
	if item then
		tries[item.id] = (tries[item.id] or 0) + 1
		PickUp(item.id)
		return
	end
	if GetTick() < loot_until then return end
	if args.limit and kills >= args.limit then
		Done("derrotei " .. kills .. " " .. args.monster)
		return
	end

	target = nearest_monster(name)
	if target ~= 0 then
		since, last_found = GetTick(), GetTick()
		Attack(target)
	elseif args.wander ~= false and not IsMoving() and GetTick() - last_found > 3000 then
		local x, y = GetV(V_POSITION, MyID)
		local a = math.random() * 2 * math.pi
		Move(x + math.floor(math.cos(a) * 10), y + math.floor(math.sin(a) * 10))
	end
end
