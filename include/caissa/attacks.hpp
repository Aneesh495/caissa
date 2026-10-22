#pragma once
#include "caissa/types.hpp"
namespace caissa::attacks {
Bitboard knight(Square s);
Bitboard king(Square s);
Bitboard pawn(Color c, Square s);
Bitboard rook(Square s, Bitboard occupied);
Bitboard bishop(Square s, Bitboard occupied);
inline Bitboard queen(Square s, Bitboard occupied) { return rook(s, occupied) | bishop(s, occupied); }
Bitboard between(Square a, Square b);
Bitboard segment(Square a, Square b);
bool validate_tables();
}
