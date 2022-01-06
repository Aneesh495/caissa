#pragma once
#include <array>
#include <bit>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace caissa {
using Bitboard = std::uint64_t;
using Key = std::uint64_t;
using Square = std::uint8_t;
inline constexpr Square no_square = 64;
inline constexpr int max_ply = 128;
inline constexpr int mate_score = 30000;
inline constexpr int mate_threshold = mate_score - max_ply;
inline constexpr int infinity = 32000;
enum class Color : std::uint8_t { white, black };
constexpr Color opposite(Color c) { return c == Color::white ? Color::black : Color::white; }
constexpr int index(Color c) { return static_cast<int>(c); }
enum class Kind : std::uint8_t { none, pawn, knight, bishop, rook, queen, king };
using Piece = std::uint8_t;
constexpr Piece piece(Color c, Kind k) {
    return k == Kind::none ? 0 : static_cast<Piece>((index(c) << 3) | static_cast<int>(k));
}
constexpr Kind kind(Piece p) { return static_cast<Kind>(p & 7U); }
constexpr Color color(Piece p) { return static_cast<Color>(p >> 3U); }
constexpr int file(Square s) { return s & 7; }
constexpr int rank(Square s) { return s >> 3; }
constexpr Square square(int f, int r) { return static_cast<Square>(r * 8 + f); }
constexpr Bitboard bit(Square s) { return s < 64 ? Bitboard{1} << s : 0; }
inline Square pop_lsb(Bitboard& b) {
    auto s = static_cast<Square>(std::countr_zero(b));
    b &= b - 1;
    return s;
}
inline std::string square_name(Square s) {
    if (s >= 64) return "-";
    return std::string{static_cast<char>('a' + file(s)), static_cast<char>('1' + rank(s))};
}
inline std::optional<Square> parse_square(std::string_view s) {
    if (s.size() != 2 || s[0] < 'a' || s[0] > 'h' || s[1] < '1' || s[1] > '8')
        return std::nullopt;
    return square(s[0] - 'a', s[1] - '1');
}
enum class MoveFlag : std::uint8_t { normal, en_passant, castle, double_push };
struct Move {
    Square from = no_square;
    Square to = no_square;
    Kind promotion = Kind::none;
    MoveFlag flag = MoveFlag::normal;
    constexpr bool valid() const { return from < 64 && to < 64; }
    constexpr bool operator==(const Move&) const = default;
    constexpr std::uint32_t packed() const {
        return from | (std::uint32_t{to} << 7) |
               (static_cast<std::uint32_t>(promotion) << 14) |
               (static_cast<std::uint32_t>(flag) << 17);
    }
    static constexpr Move unpack(std::uint32_t v) {
        return {static_cast<Square>(v & 127U), static_cast<Square>((v >> 7) & 127U),
                static_cast<Kind>((v >> 14) & 7U), static_cast<MoveFlag>((v >> 17) & 3U)};
    }
};
using Moves = std::vector<Move>;
struct InputError : std::runtime_error { using std::runtime_error::runtime_error; };
inline int mate_to_table(int score, int ply) {
    return score >= mate_threshold ? score + ply : score <= -mate_threshold ? score - ply : score;
}
inline int mate_from_table(int score, int ply) {
    return score >= mate_threshold ? score - ply : score <= -mate_threshold ? score + ply : score;
}
}
