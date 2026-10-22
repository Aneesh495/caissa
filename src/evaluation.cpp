#include "caissa/evaluation.hpp"
#include <algorithm>
#include <cmath>
namespace caissa {
namespace {
constexpr std::array<int,7> mg_value{0,100,320,335,500,950,0};
constexpr std::array<int,7> eg_value{0,120,305,335,525,920,0};
constexpr std::array<int,7> phase_value{0,0,1,1,2,4,0};
Bitboard file_mask(int f) {return 0x0101010101010101ULL<<f;}
int center_distance(Square s) {return std::abs(2*file(s)-7)+std::abs(2*rank(s)-7);}
Bitboard attacks_for(Kind k,Color c,Square s,Bitboard occ) {
    switch(k) {
        case Kind::pawn:return attacks::pawn(c,s);
        case Kind::knight:return attacks::knight(s);
        case Kind::bishop:return attacks::bishop(s,occ);
        case Kind::rook:return attacks::rook(s,occ);
        case Kind::queen:return attacks::queen(s,occ);
        case Kind::king:return attacks::king(s);
        default:return 0;
    }
}
}
int piece_value(Kind k) {return mg_value[static_cast<std::size_t>(k)];}
Evaluation evaluate_terms(const Position& p) {
    Evaluation result;
    for(Color c:{Color::white,Color::black}) {
        auto ci=static_cast<std::size_t>(index(c));auto enemy=opposite(c);
        auto& mg=result.middlegame[ci];auto& eg=result.endgame[ci];
        auto pawns=p.pieces(c,Kind::pawn),enemy_pawns=p.pieces(enemy,Kind::pawn);
        auto enemy_king=p.king(enemy),own_king=p.king(c);auto king_ring=attacks::king(enemy_king)|bit(enemy_king);
        Bitboard enemy_pawn_attacks=0,tmp=enemy_pawns;
        while(tmp) enemy_pawn_attacks|=attacks::pawn(enemy,pop_lsb(tmp));
        int attack_units=0,attackers=0;
        for(Kind k:{Kind::pawn,Kind::knight,Kind::bishop,Kind::rook,Kind::queen}) {
            auto bb=p.pieces(c,k);auto ki=static_cast<std::size_t>(k);int count=std::popcount(bb);
            mg.material+=count*mg_value[ki];eg.material+=count*eg_value[ki];result.phase+=count*phase_value[ki];
            while(bb) {
                auto s=pop_lsb(bb);int r=c==Color::white?rank(s):7-rank(s);int center=14-center_distance(s);
                auto controlled=attacks_for(k,c,s,p.occupied());
                if(k!=Kind::pawn) {
                    int mobility=std::popcount(controlled&~p.occupied(c)&~enemy_pawn_attacks);
                    int factor=k==Kind::knight?4:k==Kind::bishop?5:k==Kind::rook?2:1;
                    mg.mobility+=factor*(mobility-(k==Kind::queen?12:4));eg.mobility+=(factor+1)*(mobility-4);
                    int hits=std::popcount(controlled&king_ring);if(hits) {++attackers;attack_units+=hits*(k==Kind::queen?5:k==Kind::rook?3:2);}
                }
                if(k==Kind::pawn) {
                    mg.placement+=r*5+center*2;eg.placement+=r*7;
                    bool isolated=true;
                    if(file(s)>0&&(pawns&file_mask(file(s)-1))) isolated=false;
                    if(file(s)<7&&(pawns&file_mask(file(s)+1))) isolated=false;
                    if(isolated) {mg.pawns-=14;eg.pawns-=20;}
                    if(std::popcount(pawns&file_mask(file(s)))>1) {mg.pawns-=9;eg.pawns-=17;}
                    bool passed=true;auto others=enemy_pawns;
                    while(others) {auto t=pop_lsb(others);if(std::abs(file(t)-file(s))<=1&&(c==Color::white?rank(t)>rank(s):rank(t)<rank(s))) {passed=false;break;}}
                    if(passed) {
                        mg.pawns+=r*r*2;eg.pawns+=r*r*5;
                        int distance=std::max(std::abs(file(s)-file(own_king)),std::abs(rank(s)-rank(own_king)));
                        int enemy_distance=std::max(std::abs(file(s)-file(enemy_king)),std::abs(rank(s)-rank(enemy_king)));
                        eg.pawns+=r*(enemy_distance-distance)*2;
                    }
                    if(attacks::pawn(enemy,s)&pawns) {mg.pawns+=8+r*2;eg.pawns+=10+r*3;}
                    int next=static_cast<int>(s)+(c==Color::white?8:-8);
                    if(next>=0&&next<64&&p.at(static_cast<Square>(next))) {mg.pawns-=6;eg.pawns-=9;}
                } else if(k==Kind::knight) {
                    mg.placement+=center*6-36;eg.placement+=center*4-24;
                    if(r>=3&&r<=5&&(attacks::pawn(enemy,s)&pawns)&&!(enemy_pawn_attacks&bit(s))) mg.placement+=20;
                } else if(k==Kind::bishop) {mg.placement+=center*2;eg.placement+=center*3;}
                else if(k==Kind::rook) {
                    auto f=file_mask(file(s));if(!(pawns&f)) {mg.placement+=15;if(!(enemy_pawns&f))mg.placement+=12;}
                    if(r==6) {mg.placement+=20;eg.placement+=30;}
                } else if(k==Kind::queen) {eg.placement+=center*2;if(r>2) mg.placement-=r*2;}
            }
        }
        if(std::popcount(p.pieces(c,Kind::bishop))>=2) {mg.pairs+=28;eg.pairs+=45;}
        mg.king_safety-=center_distance(own_king)<6?25:0;
        eg.king_safety+=(14-center_distance(own_king))*6;
        int own_r=c==Color::white?rank(own_king):7-rank(own_king);
        if(own_r<=1) for(int df=-1;df<=1;++df) {
            int f=file(own_king)+df;if(f<0||f>7) continue;
            bool shelter=false;auto ps=pawns&file_mask(f);
            while(ps) {auto s=pop_lsb(ps);int r=c==Color::white?rank(s):7-rank(s);if(r>own_r&&r<=own_r+2)shelter=true;}
            if(!shelter) mg.king_safety-=18;
        }
        if(attackers>=2) result.middlegame[static_cast<std::size_t>(index(enemy))].king_safety-=std::min(250,attack_units*attackers*2);
    }
    result.phase=std::clamp(result.phase,0,24);
    int mg=result.middlegame[0].total()-result.middlegame[1].total();
    int eg=result.endgame[0].total()-result.endgame[1].total();
    result.white_score=(mg*result.phase+eg*(24-result.phase))/24;
    result.relative_score=(p.side()==Color::white?result.white_score:-result.white_score)+12;
    return result;
}
int classical(const Position& p) {return std::clamp(evaluate_terms(p).relative_score,-mate_threshold+1,mate_threshold-1);}
int static_exchange_reference(const Position& p,Move move) {
    if(move.flag==MoveFlag::castle) return 0;
    // A legal recapture sequence is the reference SEE. It includes pins and king safety.
    Position copy=p;int gain=move.flag==MoveFlag::en_passant?100:piece_value(kind(p.at(move.to)));
    if(move.promotion!=Kind::none) gain+=piece_value(move.promotion)-100;
    copy.make(move);Square target=move.to;
    std::array<int,32> values{};values[0]=gain;int depth=0;
    while(depth<30) {
        auto moves=copy.legal();std::optional<Move> least;int cost=infinity;
        for(auto m:moves) if(m.to==target&&m.flag!=MoveFlag::castle) {
            int v=kind(copy.at(m.from))==Kind::king?20000:piece_value(kind(copy.at(m.from)));
            if(v<cost) {cost=v;least=m;}
        }
        if(!least) break;
        ++depth;values[static_cast<std::size_t>(depth)]=piece_value(kind(copy.at(target)))-values[static_cast<std::size_t>(depth-1)];
        if(least->promotion!=Kind::none) values[static_cast<std::size_t>(depth)]+=piece_value(least->promotion)-100;
        copy.make(*least);
    }
    while(depth>0) {values[static_cast<std::size_t>(depth-1)]=-std::max(-values[static_cast<std::size_t>(depth-1)],values[static_cast<std::size_t>(depth)]);--depth;}
    return values[0];
}
int static_exchange(const Position& p,Move move) {
    if(move.flag==MoveFlag::castle)return 0;
    Position board=p;int initial=move.flag==MoveFlag::en_passant?100:piece_value(kind(p.at(move.to)));
    if(move.promotion!=Kind::none)initial+=piece_value(move.promotion)-100;
    board.make(move);std::array<int,32> gain{};gain[0]=initial;int depth=0;
    while(depth<30) {
        auto attackers=board.attackers_to(move.to,board.side());Move chosen;int cheapest=infinity;
        while(attackers) {
            auto from=pop_lsb(attackers);auto k=kind(board.at(from));int value=k==Kind::king?20000:piece_value(k);
            if(value>=cheapest)continue;
            Move candidate{from,move.to};
            if(k==Kind::pawn&&(rank(move.to)==0||rank(move.to)==7))candidate.promotion=Kind::queen;
            auto us=board.side();auto undo=board.make(candidate);bool legal=!board.in_check(us);board.unmake(undo);
            if(legal){chosen=candidate;cheapest=value;}
        }
        if(!chosen.valid())break;
        ++depth;gain[static_cast<std::size_t>(depth)]=piece_value(kind(board.at(move.to)))-gain[static_cast<std::size_t>(depth-1)];
        if(chosen.promotion!=Kind::none)gain[static_cast<std::size_t>(depth)]+=piece_value(chosen.promotion)-100;
        board.make(chosen);
    }
    while(depth>0){gain[static_cast<std::size_t>(depth-1)]=-std::max(-gain[static_cast<std::size_t>(depth-1)],gain[static_cast<std::size_t>(depth)]);--depth;}
    return gain[0];
}

}
