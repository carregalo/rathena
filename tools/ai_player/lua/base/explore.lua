-- Explora o mapa: anda um trecho por vez para o lado por onde ainda nao passou.
-- args: steps = quantos trechos andar antes de terminar (opcional)
local visited, steps, goal = {}, 0, nil

local function key(x, y)
	return math.floor(x / 10) .. ":" .. math.floor(y / 10)
end

local function mark(x, y, amount)
	visited[key(x, y)] = (visited[key(x, y)] or 0) + amount
end

function Tick(args)
	if IsMoving() then return end
	local x, y = GetV(V_POSITION, MyID)
	mark(x, y, 1)
	if goal and (x ~= goal[1] or y ~= goal[2]) then
		mark(goal[1], goal[2], 3)  -- nao deu para chegar (parede, agua, fim do mapa): evite esse lado
	end
	if args.steps and steps >= args.steps then
		Done("explorei " .. steps .. " trechos e parei em " .. x .. "," .. y)
		return
	end
	local best, bx, by = math.huge, x, y
	for k = 0, 7 do
		local a = k * math.pi / 4 + (math.random() - 0.5) * 0.6
		local nx = math.max(1, x + math.floor(math.cos(a) * 12))
		local ny = math.max(1, y + math.floor(math.sin(a) * 12))
		local score = (visited[key(nx, ny)] or 0) + math.random()
		if score < best then best, bx, by = score, nx, ny end
	end
	goal = { bx, by }
	steps = steps + 1
	Move(bx, by)
end
