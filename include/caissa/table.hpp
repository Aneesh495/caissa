#pragma once
#include "caissa/types.hpp"
#include <atomic>
#include <memory>
#include <mutex>
namespace caissa {
enum class Bound : std::uint8_t { none, exact, lower, upper };
struct TableEntry {
    Key key=0;
    Move move{};
    std::int16_t score=0;
    std::int16_t evaluation=0;
    std::int16_t depth=-1;
    Bound bound=Bound::none;
    std::uint8_t age=0;
};
class TranspositionTable {
public:
    explicit TranspositionTable(std::size_t megabytes=32);
    std::optional<TableEntry> probe(Key key) const;
    void store(Key key,Move move,int score,int evaluation,int depth,Bound bound,int ply);
    // Hints carry no score or bound and may cross reversible histories.
    std::optional<Move> ordering_hint(Key board_key) const;
    void store_hint(Key board_key,Move move,int depth);
    void new_search();
    void clear();
    std::size_t bytes() const {return bucket_count_*sizeof(Bucket)+hint_count_*sizeof(Hint);}
    int hashfull() const;
private:
    struct Bucket {std::array<TableEntry,4> entries;};
    struct Hint {Key key=0;Move move{};std::int16_t depth=-1;std::uint8_t age=0;};
    static constexpr std::size_t stripe_count=512;
    std::size_t bucket_count_=0;
    std::unique_ptr<Bucket[]> buckets_;
    std::size_t hint_count_=0;
    std::unique_ptr<Hint[]> hints_;
    mutable std::array<std::mutex,stripe_count> locks_;
    std::atomic<std::uint8_t> age_{0};
};
}
