#pragma once
#include "caissa/notation.hpp"
#include <iosfwd>
namespace caissa {
std::string json_quote(std::string_view text);
void write_game_json(std::ostream& out,const Game& game);
}
