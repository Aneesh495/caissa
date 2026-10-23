#include "caissa/position_line.hpp"
#include <algorithm>

namespace caissa {
PositionLine::PositionLine(bool chess960):position_(Position::from_fen(start_fen,chess960)),root_(start_fen),chess960_(chess960){}
PositionLine PositionLine::updated(std::string_view fen,std::span<const std::string> moves,bool chess960)const {
    if(moves.size()>1024)throw InputError("position history exceeds 1024 plies");
    PositionLine next=*this;next.work_={};
    std::size_t common=0;
    if(root_==fen&&chess960_==chess960) {
        auto shared=std::min(moves.size(),moves_.size());
        while(common<shared&&moves[common]==moves_[common])++common;
        next.work_.reused_plies=common;
        while(next.moves_.size()>common) {
            next.position_.unmake(next.undos_.back());
            next.undos_.pop_back();next.moves_.pop_back();++next.work_.unmade_plies;
        }
    }else {
        next.position_=Position::from_fen(fen,chess960);
        next.root_=fen;next.chess960_=chess960;
        next.moves_.clear();next.undos_.clear();
    }
    for(std::size_t index=common;index<moves.size();++index) {
        auto move=next.position_.parse_uci(moves[index]);
        if(!move)throw InputError("illegal position move");
        auto undo=next.position_.make(*move);
        next.undos_.push_back(undo);next.moves_.push_back(moves[index]);++next.work_.parsed_plies;
    }
    return next;
}
}
