#pragma once
#include "caissa/attacks.hpp"
#include <array>
#include <span>
namespace caissa {
inline constexpr std::string_view start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
using Castling = std::array<std::array<Square,2>,2>;
struct Undo {
    std::array<Square,4> squares{};
    std::array<Piece,4> pieces{};
    std::uint8_t count=0;
    Castling castling{};
    Square ep=no_square;
    std::uint32_t halfmove=0, fullmove=1;
    Key key=0;
    std::size_t history_size=0;
    Color side=Color::white;
};
class Position {
public:
    static Position from_fen(std::string_view fen, bool chess960=false);
    static Position start() { return from_fen(start_fen); }
    std::string fen() const;
    Piece at(Square s) const { return board_[s]; }
    Bitboard pieces(Color c, Kind k) const { return pieces_[static_cast<std::size_t>(index(c))][static_cast<std::size_t>(k)]; }
    Bitboard occupied(Color c) const { return colors_[static_cast<std::size_t>(index(c))]; }
    Bitboard occupied() const { return colors_[0]|colors_[1]; }
    Color side() const { return side_; }
    Square ep() const { return ep_; }
    Square king(Color c) const { return static_cast<Square>(std::countr_zero(pieces(c,Kind::king))); }
    Square rook_right(Color c, int wing) const { return castling_[static_cast<std::size_t>(index(c))][static_cast<std::size_t>(wing)]; }
    std::uint32_t halfmove() const { return halfmove_; }
    std::uint32_t fullmove() const { return fullmove_; }
    bool chess960() const { return chess960_; }
    Key key() const { return key_; }
    Key recompute_key() const;
    Key repetition_key() const;
    Key search_key() const;
    bool attacked(Square s, Color by, Bitboard occupancy) const;
    bool attacked(Square s, Color by) const { return attacked(s,by,occupied()); }
    bool in_check(Color c) const { return attacked(king(c),opposite(c)); }
    Bitboard checkers(Color c) const;
    Bitboard pinned(Color c) const;
    bool can_castle(int wing) const;
    Moves pseudo_legal() const;
    Moves legal();
    Undo make(Move m);
    void unmake(const Undo& u);
    Undo make_null();
    std::string uci(Move m) const;
    std::optional<Move> parse_uci(std::string_view text);
    int repetitions() const;
    std::span<const Key> history() const { return history_; }
    bool coherent() const;
private:
    std::array<Piece,64> board_{};
    std::array<std::array<Bitboard,7>,2> pieces_{};
    std::array<Bitboard,2> colors_{};
    Color side_=Color::white;
    Castling castling_{{{no_square,no_square},{no_square,no_square}}};
    Square ep_=no_square;
    std::uint32_t halfmove_=0, fullmove_=1;
    Key key_=0;
    bool chess960_=false;
    std::vector<Key> history_;
    Key metadata_key() const;
    void put(Square s, Piece p);
    void save_square(Undo& u, Square s);
    Undo save_state() const;
};
std::uint64_t perft(Position& p, int depth);
std::vector<std::pair<std::string,std::uint64_t>> divide(Position& p, int depth);
}
