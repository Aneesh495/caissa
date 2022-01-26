#include "caissa/table.hpp"
#include <algorithm>
namespace caissa {
TranspositionTable::TranspositionTable(std::size_t megabytes) {
    if(megabytes<1||megabytes>1024) throw InputError("Hash must be in [1,1024] MiB");
    bucket_count_=std::bit_floor(megabytes*1024*1024/sizeof(Bucket));
    buckets_=std::make_unique<Bucket[]>(bucket_count_);
}
std::optional<TableEntry> TranspositionTable::probe(Key key) const {
    auto bucket=static_cast<std::size_t>(key)&(bucket_count_-1);
    std::lock_guard lock(locks_[bucket%stripe_count]);
    for(auto& e:buckets_[bucket].entries) if(e.bound!=Bound::none&&e.key==key) return e;
    return std::nullopt;
}
void TranspositionTable::store(Key key,Move move,int score,int evaluation,int depth,Bound bound,int ply) {
    auto bucket=static_cast<std::size_t>(key)&(bucket_count_-1);
    std::lock_guard lock(locks_[bucket%stripe_count]);
    auto age=age_.load(std::memory_order_relaxed);auto& entries=buckets_[bucket].entries;
    TableEntry* victim=&entries[0];int worst=100000;
    for(auto& e:entries) {
        if(e.bound==Bound::none) {victim=&e;break;}
        if(e.key==key) {victim=&e;break;}
        int retention=e.depth-8*static_cast<int>(static_cast<std::uint8_t>(age-e.age));
        if(retention<worst) {worst=retention;victim=&e;}
    }
    if(victim->key==key&&victim->bound!=Bound::none&&victim->depth>depth+3&&bound!=Bound::exact) {
        if(move.valid()) victim->move=move;
        return;
    }
    if(!move.valid()&&victim->key==key) move=victim->move;
    *victim={key,move,static_cast<std::int16_t>(mate_to_table(score,ply)),static_cast<std::int16_t>(evaluation),static_cast<std::int16_t>(depth),bound,age};
}
void TranspositionTable::new_search() {age_.fetch_add(1,std::memory_order_relaxed);}
void TranspositionTable::clear() {
    for(std::size_t b=0;b<bucket_count_;++b) {std::lock_guard lock(locks_[b%stripe_count]);buckets_[b]=Bucket{};}
}
int TranspositionTable::hashfull() const {
    auto count=std::min<std::size_t>(250,bucket_count_);std::size_t filled=0;
    for(std::size_t b=0;b<count;++b) {
        std::lock_guard lock(locks_[b%stripe_count]);
        for(auto& e:buckets_[b].entries) if(e.bound!=Bound::none&&e.age==age_.load(std::memory_order_relaxed))++filled;
    }
    return static_cast<int>(filled*1000/(count*4));
}
}
