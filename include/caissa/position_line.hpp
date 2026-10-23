#pragma once
#include "caissa/position.hpp"

namespace caissa {
struct PositionLineWork {
    std::size_t reused_plies=0,unmade_plies=0,parsed_plies=0;
};
// A validated UCI root and move prefix. Updates return a complete new value;
// malformed suffixes cannot alter the currently installed game/history.
class PositionLine {
public:
    explicit PositionLine(bool chess960=false);
    PositionLine updated(std::string_view fen,std::span<const std::string> moves,bool chess960)const;
    const Position& current()const{return position_;}
    PositionLineWork work()const{return work_;}
private:
    Position position_;
    std::string root_;
    bool chess960_=false;
    std::vector<std::string> moves_;
    std::vector<Undo> undos_;
    PositionLineWork work_;
};
}
