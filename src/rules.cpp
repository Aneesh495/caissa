#include "caissa/rules.hpp"
namespace caissa {
bool proven_dead(const Position& p) {
    auto pawns=p.pieces(Color::white,Kind::pawn)|p.pieces(Color::black,Kind::pawn);
    auto rooks=p.pieces(Color::white,Kind::rook)|p.pieces(Color::black,Kind::rook);
    auto queens=p.pieces(Color::white,Kind::queen)|p.pieces(Color::black,Kind::queen);
    if(pawns||rooks||queens) return false;
    auto knights=p.pieces(Color::white,Kind::knight)|p.pieces(Color::black,Kind::knight);
    auto bishops=p.pieces(Color::white,Kind::bishop)|p.pieces(Color::black,Kind::bishop);
    if(std::popcount(knights|bishops)<=1) return true;
    if(knights) return false;
    constexpr Bitboard light=0x55aa55aa55aa55aaULL;
    return !(bishops&light)||!(bishops&~light);
}
namespace {
RuleState continuing_rules(Position& p) {
    RuleState state;
    if(p.synthetic_search_path()){if(proven_dead(p))state.terminal=Termination::proven_dead;return state;}
    if(p.halfmove()>=150){state.terminal=Termination::seventy_five;return state;}
    int count=p.repetitions();
    if(count>=5){state.terminal=Termination::fivefold;return state;}
    if(proven_dead(p)){state.terminal=Termination::proven_dead;return state;}
    state.threefold_claim=count>=3;state.fifty_move_claim=p.halfmove()>=100;return state;
}
}
RuleState rules(Position& p,const Moves& legal_moves) {
    if(legal_moves.empty()){RuleState state;state.terminal=p.in_check(p.side())?Termination::checkmate:Termination::stalemate;return state;}
    return continuing_rules(p);
}
RuleState rules(Position& p,const MoveAvailability& availability) {
    if(availability.position_key()!=p.key())throw InputError("legal availability belongs to a different position");
    if(!availability.any()){RuleState state;state.terminal=availability.checked()?Termination::checkmate:Termination::stalemate;return state;}
    return continuing_rules(p);
}
RuleState rules(Position& p){return rules(p,p.availability());}
Moves claim_by_move(Position& p) {
    Moves result;
    if(rules(p).ended()) return result;
    for(auto m:p.legal()) {
        auto u=p.make(m);auto after=rules(p);p.unmake(u);
        if(after.claimable()&&!after.ended()) result.push_back(m);
    }
    return result;
}
Move intended_claim_move(Position& p,const Moves& supplied) {
    if(p.synthetic_search_path())return {};
    bool possible=p.halfmove()==99;
    auto history=p.history();auto count=std::min(history.size(),static_cast<std::size_t>(p.halfmove())+1);
    // The next side to move must have occurred twice. Screen only that
    // parity of the reversible window before inspecting legal continuations.
    if(!possible&&count>=8) {
        auto begin=history.size()-count;
        for(std::size_t i=history.size()-2;i>=begin+2&&!possible;i-=2) {
            for(std::size_t j=i-2;;j-=2){if(history[i]==history[j]){possible=true;break;}if(j<begin+2)break;}
            if(i<begin+4)break;
        }
    }
    if(!possible)return {};
    auto generated=supplied.empty()?p.legal():Moves{};
    const auto& moves=supplied.empty()?generated:supplied;
    for(auto move:moves) {
        auto undo=p.make(move);auto state=rules(p);p.unmake(undo);
        if(state.claimable()&&!state.ended())return move;
    }
    return {};
}
std::string_view termination_name(Termination t) {
    switch(t) {
        case Termination::ongoing:return "ongoing";
        case Termination::checkmate:return "checkmate";
        case Termination::stalemate:return "stalemate";
        case Termination::fivefold:return "fivefold";
        case Termination::seventy_five:return "seventy-five-move";
        case Termination::proven_dead:return "proven-dead-material";
    }
    return "invalid";
}
}
