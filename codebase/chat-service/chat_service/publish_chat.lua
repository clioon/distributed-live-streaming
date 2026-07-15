local existing = redis.call("GET", KEYS[2])
if existing then
    return {0, existing}
end

local sequence = redis.call("INCR", KEYS[1])
local message = cjson.decode(ARGV[2])
message["sequence"] = sequence
local encoded = cjson.encode(message)

redis.call("SET", KEYS[2], encoded, "EX", ARGV[3])
redis.call("PUBLISH", ARGV[1], encoded)

return {1, encoded}