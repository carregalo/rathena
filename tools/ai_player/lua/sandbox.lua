-- Sandbox for the agent's own routines (tools/ai_player/lua). It has nothing to do with the game client's
-- AI/*.lua files, which stay untouched; it only borrows their shape: a few primitive actions offered by the
-- engine, and routines that decide when to call them, once per tick.
--
-- Routines run in their own environment with a copy of the safe standard libraries plus the game API.
-- No io, os, load, require, debug, metatables or pcall: a routine cannot touch the machine, and a runaway
-- loop is stopped by the instruction hook below (pcall is left out so a routine cannot swallow that stop).

local LIMIT = 200000  -- instructions per call before a routine is stopped

local function copy(t)
	local c = {}
	for k, v in pairs(t) do c[k] = v end
	return c
end

local sandbox = {}

function sandbox.new_env(api)
	local base = {
		math = copy(math), string = copy(string), table = copy(table),
		pairs = pairs, ipairs = ipairs, next = next, select = select, type = type,
		tostring = tostring, tonumber = tonumber, error = error, assert = assert,
	}
	for k, v in pairs(api) do base[k] = v end
	return setmetatable({}, { __index = base })
end

local function guarded(fn, ...)
	debug.sethook(function() error("a rotina passou do limite de instrucoes (laco sem fim?)", 2) end, "", LIMIT)
	local result = table.pack(pcall(fn, ...))
	debug.sethook()
	return table.unpack(result, 1, result.n)
end

-- Compiles a routine into env and runs its top level. Returns ok, error message.
function sandbox.load(code, name, env)
	local chunk, err = load(code, "=" .. name, "t", env)
	if not chunk then return false, err end
	local ok, run_err = guarded(chunk)
	if not ok then return false, run_err end
	if type(rawget(env, "Tick")) ~= "function" then
		return false, "a rotina precisa definir function Tick(args)"
	end
	return true, nil
end

-- Calls env[fname](args) if the routine defines it. Returns ok, error message.
function sandbox.call(env, fname, args)
	local fn = rawget(env, fname)
	if type(fn) ~= "function" then return true, nil end
	local ok, err = guarded(fn, args)
	return ok, err
end

return sandbox
