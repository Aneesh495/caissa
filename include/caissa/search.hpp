#pragma once
#include "caissa/evaluation.hpp"
#include "caissa/network.hpp"
#include "caissa/rules.hpp"
#include "caissa/table.hpp"
#include <chrono>
#include <functional>
#include <memory>
namespace caissa {
struct SearchOptions {
    bool table=true, pvs=true, aspiration=true, quiescence=true;
    bool null_move=true, lmr=true, extensions=true, history=true, see=true;
    bool futility=true;
    int threads=1, multipv=1,trace_limit=0;
    std::shared_ptr<const Network> network;
    bool scalar_network=false;
};
struct Limits {
    int depth=64;
    std::uint64_t nodes=0;
    std::int64_t milliseconds=0;
    bool infinite=false,ponder=false;
    Moves root_moves;
};
struct SearchControl {
    std::atomic<bool> stop{false};
    std::atomic<bool> pondering{false};
    std::atomic<std::uint64_t> nodes{0};
    std::atomic<std::int64_t> deadline_ns{INT64_MAX};
    std::uint64_t node_limit=0;
    std::atomic<std::int64_t> ponder_budget_ms{0};
    std::atomic<bool> ponder_hit_requested{false};
    std::once_flag initialize_once;
    void initialize(const Limits& limits);
    void ponderhit();
};
struct SearchStats {
    std::uint64_t qnodes=0,table_hits=0,table_cutoffs=0,beta_cutoffs=0;
    std::uint64_t null_cutoffs=0,lmr_searches=0,researches=0,futility_skips=0;
    std::uint64_t evaluator_calls=0,evaluator_ns=0;
    int seldepth=0;
    SearchStats& operator+=(const SearchStats& rhs);
};
struct PrincipalLine {Move move{};int score=0;Moves pv;Bound bound=Bound::exact;};
struct TraceSample {std::string fen;int depth,alpha,beta,ply;bool synthetic;};
struct SearchInfo {
    int depth=0;
    std::uint64_t nodes=0,completed_depth_nodes=0;
    std::int64_t elapsed_ms=0;
    int hashfull=0;
    SearchStats stats;
    std::vector<PrincipalLine> lines;
    std::vector<TraceSample> trace;
};
struct SearchResult {Move best{};int score=0;Moves pv;SearchInfo info;bool interrupted=false;};
using InfoCallback=std::function<void(const SearchInfo&)>;
class Search {
public:
    explicit Search(std::shared_ptr<TranspositionTable> table):table_(std::move(table)){}
    SearchResult run(Position root,const Limits& limits,const SearchOptions& options,
                     std::shared_ptr<SearchControl> control,const InfoCallback& callback={});
private:
    std::shared_ptr<TranspositionTable> table_;
};
std::int64_t monotonic_ns();
std::int64_t time_budget(std::int64_t remaining,std::int64_t increment,int moves_to_go,int overhead);
}
