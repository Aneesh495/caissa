#pragma once
#include "caissa/position.hpp"
namespace caissa::reference {
Moves legal(const Position& position);
std::uint64_t perft(const Position& position, int depth);
}
