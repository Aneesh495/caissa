#pragma once
#include "caissa/position.hpp"
namespace caissa {
enum class Termination { ongoing, checkmate, stalemate, fivefold, seventy_five, proven_dead };
struct RuleState {
    Termination terminal=Termination::ongoing;
    bool threefold_claim=false;
    bool fifty_move_claim=false;
    bool ended() const { return terminal!=Termination::ongoing; }
    bool claimable() const { return threefold_claim||fifty_move_claim; }
};
bool proven_dead(const Position& p);
RuleState rules(Position& p, const Moves& legal_moves);
RuleState rules(Position& p,const MoveAvailability& availability);
RuleState rules(Position& p);
Moves claim_by_move(Position& p);
std::string_view termination_name(Termination t);
}
