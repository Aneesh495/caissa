#include "caissa/attacks.hpp"
#include <algorithm>
#include <cmath>
namespace caissa::attacks {
namespace {
struct Tables {
    std::array<Bitboard, 64> knights{}, kings{};
    std::array<std::array<Bitboard, 64>, 2> pawns{};
    std::array<std::array<Bitboard, 8>, 64> rays{};
    static constexpr std::array<int, 8> df{1,-1,0,0,1,-1,1,-1};
    static constexpr std::array<int, 8> dr{0,0,1,-1,1,1,-1,-1};
    Tables() {
        for (int s = 0; s < 64; ++s) {
            auto sq = static_cast<Square>(s);
            for (int d = 0; d < 8; ++d) {
                int f = file(sq) + df[static_cast<std::size_t>(d)];
                int r = rank(sq) + dr[static_cast<std::size_t>(d)];
                while (f >= 0 && f < 8 && r >= 0 && r < 8) {
                    rays[static_cast<std::size_t>(s)][static_cast<std::size_t>(d)] |= bit(square(f,r));
                    f += df[static_cast<std::size_t>(d)];
                    r += dr[static_cast<std::size_t>(d)];
                }
            }
            for (int f = 0; f < 8; ++f) for (int r = 0; r < 8; ++r) {
                int dx = std::abs(f-file(sq)), dy = std::abs(r-rank(sq));
                if (dx*dy == 2) knights[static_cast<std::size_t>(s)] |= bit(square(f,r));
                if (std::max(dx,dy) == 1) kings[static_cast<std::size_t>(s)] |= bit(square(f,r));
                for (int c = 0; c < 2; ++c)
                    if (dx == 1 && r-rank(sq) == (c == 0 ? 1 : -1))
                        pawns[static_cast<std::size_t>(c)][static_cast<std::size_t>(s)] |= bit(square(f,r));
            }
        }
    }
};
const Tables tables;
Bitboard sliding(Square s, Bitboard occupied, int first, int end) {
    Bitboard result = 0;
    for (int d = first; d < end; ++d) {
        auto ray = tables.rays[s][static_cast<std::size_t>(d)];
        auto blocked = ray & occupied;
        if (blocked) {
            bool increasing = Tables::dr[static_cast<std::size_t>(d)] > 0 ||
                              (Tables::dr[static_cast<std::size_t>(d)] == 0 && Tables::df[static_cast<std::size_t>(d)] > 0);
            auto stop = static_cast<Square>(increasing ? std::countr_zero(blocked) : 63-std::countl_zero(blocked));
            ray ^= tables.rays[stop][static_cast<std::size_t>(d)];
        }
        result |= ray;
    }
    return result;
}
}
Bitboard knight(Square s) { return tables.knights[s]; }
Bitboard king(Square s) { return tables.kings[s]; }
Bitboard pawn(Color c, Square s) { return tables.pawns[static_cast<std::size_t>(index(c))][s]; }
Bitboard rook(Square s, Bitboard o) { return sliding(s,o,0,4); }
Bitboard bishop(Square s, Bitboard o) { return sliding(s,o,4,8); }
Bitboard between(Square a, Square b) {
    int dx=file(b)-file(a), dy=rank(b)-rank(a);
    if (a == b || !(dx == 0 || dy == 0 || std::abs(dx) == std::abs(dy))) return 0;
    int df=(dx>0)-(dx<0), dr=(dy>0)-(dy<0);
    Bitboard v=0;
    for (int f=file(a)+df,r=rank(a)+dr; f!=file(b)||r!=rank(b); f+=df,r+=dr) v |= bit(square(f,r));
    return v;
}
Bitboard segment(Square a, Square b) { return between(a,b) | bit(a) | bit(b); }
bool validate_tables() {
    std::uint64_t state=1729;
    for (int n=0;n<4096;++n) {
        state ^= state << 13; state ^= state >> 7; state ^= state << 17;
        for (int s=0;s<64;++s) for (int group=0;group<2;++group) {
            Bitboard expected=0;
            for (int d=group*4;d<(group+1)*4;++d) {
                int f=(s&7)+Tables::df[static_cast<std::size_t>(d)];
                int r=(s>>3)+Tables::dr[static_cast<std::size_t>(d)];
                while(f>=0&&f<8&&r>=0&&r<8) {
                    auto b=bit(square(f,r)); expected|=b;
                    if (state&b) break;
                    f+=Tables::df[static_cast<std::size_t>(d)]; r+=Tables::dr[static_cast<std::size_t>(d)];
                }
            }
            if (sliding(static_cast<Square>(s),state,group*4,(group+1)*4)!=expected) return false;
        }
    }
    return true;
}
}
