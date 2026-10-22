#pragma once
#include "caissa/position.hpp"
#include <map>
namespace caissa {
std::string san(Position& position,Move move);
std::optional<Move> parse_san(Position& position,std::string_view token);
struct VariationNode {
    std::size_t parent=0;
    Move move{};
    std::vector<std::size_t> children;
    std::string comment;
    std::vector<int> nags;
};
class Game {
public:
    std::map<std::string,std::string> tags;
    std::vector<VariationNode> nodes{VariationNode{}};
    std::string result="*";
    Position initial=Position::start();
    static Game parse(std::string_view pgn);
    std::size_t append(std::size_t parent,Move move);
    Position position_at(std::size_t node) const;
    std::string pgn() const;
};
}
