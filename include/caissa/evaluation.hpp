#pragma once
#include "caissa/position.hpp"
namespace caissa {
struct EvalTerms {
    int material=0, placement=0, pawns=0, mobility=0, king_safety=0, pairs=0;
    int total() const {return material+placement+pawns+mobility+king_safety+pairs;}
};
struct Evaluation {
    std::array<EvalTerms,2> middlegame{},endgame{};
    int phase=0;
    int white_score=0;
    int relative_score=0;
};
Evaluation evaluate_terms(const Position& p);
int classical(const Position& p);
int piece_value(Kind k);
int static_exchange(const Position& p,Move move);
int static_exchange_reference(const Position& p,Move move);
}
