#pragma once
#include "caissa/types.hpp"
#include <array>
#include <optional>

namespace caissa {
// Exact static evaluations only. Each search worker owns its own cache, so its
// network, deployment percentage and evaluation contract cannot change lifetime.
// Board hash collisions have the same full 64-bit identity assumption as the TT.
class EvaluationCache {
public:
    static constexpr std::size_t capacity=32768;
    std::optional<int> find(Key key) const noexcept {
        const auto& entry=entries_[static_cast<std::size_t>(key)&(capacity-1)];
        if(entry.valid&&entry.key==key)return entry.score;
        return std::nullopt;
    }
    void store(Key key,int score) {
        if(score<=-mate_threshold||score>=mate_threshold)
            throw InputError("evaluation cache requires an exact non-mate static score");
        entries_[static_cast<std::size_t>(key)&(capacity-1)]={key,score,true};
    }
    std::size_t bytes() const noexcept {return sizeof(entries_);}
private:
    struct Entry {Key key=0;int score=0;bool valid=false;};
    std::array<Entry,capacity> entries_{};
};
}
