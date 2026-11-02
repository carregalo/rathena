// Helpers shared by the protocol dump tools: print JSON objects with struct sizes and field offsets computed by
// the compiler (offsetof), so the specification never relies on hand-counted bytes.
#pragma once
#include <cstddef>
#include <cstdio>

static bool first_struct = true, first_field = true;

#define STRUCT_BEGIN(s) std::printf("%s\n    \"%s\": {\"size\": %d, \"fields\": {", first_struct ? "" : ",", #s, (int)sizeof(struct s)); first_struct = false; first_field = true
#define FIELD(s, f) std::printf("%s\"%s\": %d", first_field ? "" : ", ", #f, (int)offsetof(struct s, f)); first_field = false
#define STRUCT_END() std::printf("}}")
