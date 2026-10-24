#include "caissa/thread.hpp"
#include "caissa/search.hpp"
#include "caissa/evaluation_cache.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <exception>
#include <mutex>
#include <thread>
#include <random>
namespace caissa {
std::int64_t monotonic_ns() {return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void SearchControl::initialize(const Limits& limits) {
    std::call_once(initialize_once,[&] {
        node_limit=limits.nodes;ponder_budget_ms.store(limits.milliseconds);
        pondering.store(limits.ponder&&!ponder_hit_requested.load());
        if(limits.milliseconds>0&&!pondering.load()&&!limits.infinite)
            deadline_ns.store(monotonic_ns()+limits.milliseconds*1000000);
        // A hit racing initialization must not be overwritten by the initial ponder state.
        if(ponder_hit_requested.load())ponderhit();
    });
}
void SearchControl::ponderhit() {
    ponder_hit_requested.store(true);pondering.store(false,std::memory_order_release);
    auto budget=ponder_budget_ms.load();
    if(budget>0)deadline_ns.store(monotonic_ns()+budget*1000000,std::memory_order_relaxed);
}
std::int64_t time_budget(std::int64_t remaining,std::int64_t increment,int moves_to_go,int overhead) {
    auto available=std::max<std::int64_t>(1,remaining-overhead);
    auto allocation=available/std::clamp(moves_to_go,1,60)+increment*3/4;
    return std::clamp<std::int64_t>(allocation,1,std::max<std::int64_t>(1,available/2));
}
SearchStats& SearchStats::operator+=(const SearchStats& r) {
    neural_evaluations+=r.neural_evaluations;neural_bound_cutoffs+=r.neural_bound_cutoffs;
    evaluation_cache_hits+=r.evaluation_cache_hits;evaluation_cache_bytes+=r.evaluation_cache_bytes;
    ordering_hint_hits+=r.ordering_hint_hits;qnodes+=r.qnodes;table_hits+=r.table_hits;table_cutoffs+=r.table_cutoffs;beta_cutoffs+=r.beta_cutoffs;
    null_cutoffs+=r.null_cutoffs;lmr_searches+=r.lmr_searches;researches+=r.researches;futility_skips+=r.futility_skips;
    evaluator_calls+=r.evaluator_calls;evaluator_ns+=r.evaluator_ns;seldepth=std::max(seldepth,r.seldepth);return *this;
}
namespace {
int evaluation_of(const Position& p,const SearchOptions& options,const Accumulator* accumulator) {
    if(!options.network||options.neural_weight==0)return classical(p);
    return options.network->evaluate(p,*accumulator,options.scalar_network,options.neural_weight);
}
struct Abort {};
struct Guard {
    Position& p;Undo undo;Accumulator* accumulator;Accumulator saved;
    Guard(Position& pos,Move move,const Network* net,Accumulator* acc):p(pos),undo(p.make(move)),accumulator(acc) {
        if(net){saved=*acc;net->update(p,undo,*acc);}
    }
    Guard(Position& pos,const Network* net,Accumulator* acc):p(pos),undo(p.make_null()),accumulator(acc) {
        if(net){saved=*acc;net->update(p,undo,*acc);}
    }
    ~Guard(){p.unmake(undo);if(accumulator)*accumulator=saved;}
    Guard(const Guard&)=delete;Guard& operator=(const Guard&)=delete;
};
class Worker {
public:
    Worker(TranspositionTable& table,SearchControl& control,const SearchOptions& options):table_(table),control_(control),options_(options) {
        if(options_.evaluation_cache){evaluation_cache_=std::make_unique<EvaluationCache>();stats.evaluation_cache_bytes=evaluation_cache_->bytes();}
    }
    SearchStats stats;
    std::vector<TraceSample> trace;
    void reset(const Position& p){if(options_.network)accumulator_=options_.network->refresh(p);}
    int visit(Position& p,int depth,int alpha,int beta,int ply,bool allow_null,Move previous,Moves& pv) {
        touch(ply);pv.clear();
        if(depth>=2&&trace.size()<static_cast<std::size_t>(options_.trace_limit))trace.push_back({p.fen(),depth,alpha,beta,ply,p.synthetic_search_path()});
        if(ply>=max_ply-1) return evaluate(p);
        auto prepared=prepare_position(p,depth<=0);
        bool check=prepared.checked;auto moves=std::move(prepared.moves);auto state=prepared.state;
        if(state.ended()) return state.terminal==Termination::checkmate?-mate_score+ply:0;
        bool claim=state.claimable();
        if(claim) {if(beta<=0)return 0;alpha=std::max(alpha,0);}
        if(depth<=0) {
            if(!options_.quiescence) return std::max(claim?0:-infinity,evaluate(p));
            return quiet(p,alpha,beta,ply,0,claim,std::move(moves),pv,check,prepared.tactical_pending);
        }
        alpha=std::max(alpha,-mate_score+ply);beta=std::min(beta,mate_score-ply-1);
        if(alpha>=beta) return alpha;
        int original_alpha=alpha;Key key=p.search_key();std::optional<TableEntry> entry;
        Move hashmove;bool pv_node=beta-alpha>1;
        if(options_.table) entry=table_.probe(key);
        if(entry) {
            ++stats.table_hits;hashmove=entry->move;
            int score=mate_from_table(entry->score,ply);
            if(entry->depth>=depth&&!pv_node&&(entry->bound==Bound::exact||(entry->bound==Bound::lower&&score>=beta)||(entry->bound==Bound::upper&&score<=alpha))) {
                ++stats.table_cutoffs;return score;
            }
        }
        if(!hashmove.valid()&&options_.table&&options_.ordering_hints) {
            auto hint=table_.ordering_hint(p.key());
            if(hint&&std::find(moves.begin(),moves.end(),*hint)!=moves.end()) {
                hashmove=*hint;++stats.ordering_hint_hits;
            }
        }
        int evaluation=entry?entry->evaluation:evaluate(p);
        bool non_pawn=(p.occupied(p.side())&~p.pieces(p.side(),Kind::pawn)&~p.pieces(p.side(),Kind::king))!=0;
        if(options_.null_move&&allow_null&&!pv_node&&!check&&!claim&&depth>=3&&non_pawn&&p.halfmove()<90&&evaluation>=beta&&std::abs(beta)<mate_threshold) {
            int reduction=2+depth/5;Moves ignored;int score;
            {Guard guard(p,options_.network.get(),options_.network?&accumulator_:nullptr);score=-visit(p,std::max(0,depth-1-reduction),-beta,-beta+1,ply+1,false,{},ignored);}
            if(score>=beta) {
                if(depth>=7) {score=visit(p,depth-reduction,beta-1,beta,ply,false,previous,ignored);}
                if(score>=beta) {++stats.null_cutoffs;return std::min(score,mate_threshold-1);}
            }
        }
        order(p,moves,hashmove,previous,ply);
        int best=claim?0:-infinity;Move bestmove;int searched=0;Moves quiets;
        for(auto move:moves) {
            bool capture=is_capture(p,move),promotion=move.promotion!=Kind::none;
            if(options_.futility&&!pv_node&&!check&&!claim&&depth<=2&&searched>0&&!capture&&!promotion&&evaluation+110*depth<=alpha&&std::abs(alpha)<mate_threshold) {
                Guard guard(p,move,options_.network.get(),options_.network?&accumulator_:nullptr);if(!p.in_check(p.side())) {++stats.futility_skips;continue;}
            }
            int score;Moves child;bool gives_check;
            {Guard guard(p,move,options_.network.get(),options_.network?&accumulator_:nullptr);gives_check=p.in_check(p.side());
                int extension=options_.extensions&&check&&ply<16&&depth>1?1:0;
                int next_depth=depth-1+extension;
                int reduction=0;
                if(options_.lmr&&searched>=3&&depth>=3&&!check&&!gives_check&&!capture&&!promotion)
                    reduction=std::min(next_depth-1,1+(depth>=6&&searched>=8?1:0)+(pv_node?0:1));
                if(reduction>0) {
                    ++stats.lmr_searches;score=-visit(p,next_depth-reduction,-alpha-1,-alpha,ply+1,true,move,child);
                    if(score>alpha) {++stats.researches;score=-visit(p,next_depth,-alpha-1,-alpha,ply+1,true,move,child);}
                } else if(options_.pvs&&searched>0) score=-visit(p,next_depth,-alpha-1,-alpha,ply+1,true,move,child);
                else score=-visit(p,next_depth,-beta,-alpha,ply+1,true,move,child);
                if(options_.pvs&&searched>0&&score>alpha&&score<beta) {++stats.researches;score=-visit(p,next_depth,-beta,-alpha,ply+1,true,move,child);}
            }
            ++searched;
            if(score>best) {best=score;bestmove=move;pv={move};pv.insert(pv.end(),child.begin(),child.end());}
            if(score>alpha) alpha=score;
            if(alpha>=beta) {
                ++stats.beta_cutoffs;
                if(!capture&&!promotion&&options_.history) {
                    auto pi=static_cast<std::size_t>(ply);
                    if(killers_[pi][0]!=move) {killers_[pi][1]=killers_[pi][0];killers_[pi][0]=move;}
                    if(previous.valid()) counters_[previous.from][previous.to]=move;
                    int bonus=std::min(1600,depth*depth*32);update_history(p.side(),move,bonus);
                    for(auto q:quiets) update_history(p.side(),q,-bonus/2);
                }
                break;
            }
            if(!capture&&!promotion) quiets.push_back(move);
        }
        if(options_.table&&options_.ordering_hints)table_.store_hint(p.key(),bestmove,depth);
        if(options_.table) table_.store(key,bestmove,best,evaluation,depth,best>=beta?Bound::lower:best<=original_alpha?Bound::upper:Bound::exact,ply);
        return best;
    }
private:
    TranspositionTable& table_;SearchControl& control_;const SearchOptions& options_;
    std::array<std::array<Move,2>,max_ply> killers_{};
    std::array<std::array<Move,64>,64> counters_{};
    std::array<std::array<std::array<int,64>,64>,2> history_{};
    std::uint64_t local_nodes_=0;Accumulator accumulator_;
    std::unique_ptr<EvaluationCache> evaluation_cache_;
    struct PreparedPosition {RuleState state;bool checked,tactical_pending;Moves moves;};
    PreparedPosition prepare_position(Position& p,bool leaf) {
        if(leaf&&options_.tactical_generation) {
            auto available=p.availability();auto state=rules(p,available);Moves moves;
            if(available.checked()&&!state.ended())moves=p.legal();
            return {state,available.checked(),!available.checked(),std::move(moves)};
        }
        bool checked=p.in_check(p.side());auto moves=p.legal();auto state=rules(p,moves);
        return {state,checked,false,std::move(moves)};
    }
    void touch(int ply) {
        if(control_.stop.load(std::memory_order_relaxed)) throw Abort{};
        auto ticket=control_.nodes.fetch_add(1,std::memory_order_relaxed);
        if(control_.node_limit&&ticket>=control_.node_limit) {control_.stop.store(true,std::memory_order_relaxed);throw Abort{};}
        if((++local_nodes_&63U)==0&&monotonic_ns()>=control_.deadline_ns.load(std::memory_order_relaxed)) {control_.stop.store(true,std::memory_order_relaxed);throw Abort{};}
        stats.seldepth=std::max(stats.seldepth,ply);
    }
    int evaluate(const Position& p,int stand_pat_beta=infinity) {
        auto begin=monotonic_ns();int score;bool exact=true;
        ++stats.evaluator_calls;
        if(evaluation_cache_) {
            if(auto cached=evaluation_cache_->find(p.key())) {
                ++stats.evaluation_cache_hits;
                stats.evaluator_ns+=static_cast<std::uint64_t>(monotonic_ns()-begin);
                return *cached;
            }
        }
        if(options_.neural_bounds&&options_.network&&options_.network->residual()&&
           options_.neural_weight>0&&stand_pat_beta<infinity) {
            auto result=options_.network->evaluate_at_least(p,accumulator_,stand_pat_beta,
                                                          options_.scalar_network,options_.neural_weight);
            score=result.score;exact=result.exact;
            if(result.exact)++stats.neural_evaluations;else ++stats.neural_bound_cutoffs;
        } else {
            score=evaluation_of(p,options_,&accumulator_);
            if(options_.network&&options_.neural_weight>0)++stats.neural_evaluations;
        }
        if(evaluation_cache_&&exact)evaluation_cache_->store(p.key(),score);
        stats.evaluator_ns+=static_cast<std::uint64_t>(monotonic_ns()-begin);return score;
    }
    bool is_capture(const Position& p,Move m) const {return m.flag==MoveFlag::en_passant||(m.flag!=MoveFlag::castle&&p.at(m.to));}
    void update_history(Color c,Move m,int bonus) {
        auto& h=history_[static_cast<std::size_t>(index(c))][m.from][m.to];h+=bonus-h*std::abs(bonus)/16384;
    }
    void order(const Position& p,Moves& moves,Move hash,Move previous,int ply) {
        std::vector<std::pair<int,Move>> ordered;ordered.reserve(moves.size());
        for(auto m:moves) {
            int score=0;
            if(m==hash) score=2000000;
            else if(is_capture(p,m)) {
                int victim=m.flag==MoveFlag::en_passant?100:piece_value(kind(p.at(m.to)));
                int attacker=piece_value(kind(p.at(m.from)));
                int see=options_.see?static_exchange(p,m):victim-attacker;
                score=(see>=0?1000000:-100000)+victim*16-attacker;
            } else if(m.promotion!=Kind::none) score=900000+piece_value(m.promotion);
            else if(options_.history) {
                auto pi=static_cast<std::size_t>(ply);
                if(m==killers_[pi][0]) score=800000;
                else if(m==killers_[pi][1]) score=790000;
                else if(previous.valid()&&m==counters_[previous.from][previous.to]) score=780000;
                else score=history_[static_cast<std::size_t>(index(p.side()))][m.from][m.to];
            }
            ordered.emplace_back(score,m);
        }
        std::stable_sort(ordered.begin(),ordered.end(),[](auto& a,auto& b){return a.first>b.first;});
        for(std::size_t i=0;i<moves.size();++i) moves[i]=ordered[i].second;
    }
    int quiet(Position& p,int alpha,int beta,int ply,int qply,bool claim,Moves moves,Moves& pv,bool check,bool tactical_pending) {
        ++stats.qnodes;
        int best=claim?0:-infinity;
        // A certified evaluation lower bound is usable only as a stand-pat
        // cutoff outside check. Principal/full evaluations remain exact.
        if(!check) {best=std::max(best,evaluate(p,beta));if(best>=beta)return best;alpha=std::max(alpha,best);}
        if(qply>=24||ply>=max_ply-2) return check?evaluate(p):best;
        if(!check) {
            if(tactical_pending)moves=p.legal_tactical();
            else std::erase_if(moves,[&](Move m){return !is_capture(p,m)&&m.promotion==Kind::none;});
        }
        order(p,moves,{}, {},ply);
        for(auto m:moves) {
            if(!check&&!is_capture(p,m)&&m.promotion==Kind::none)continue;
            Moves child;int score;
            {Guard guard(p,m,options_.network.get(),options_.network?&accumulator_:nullptr);touch(ply+1);auto prepared=prepare_position(p,true);auto state=prepared.state;
                if(state.ended()) score=state.terminal==Termination::checkmate?mate_score-ply-1:0;
                else score=-quiet(p,-beta,-alpha,ply+1,qply+1,state.claimable(),std::move(prepared.moves),child,prepared.checked,prepared.tactical_pending);
            }
            if(score>best) {best=score;pv={m};pv.insert(pv.end(),child.begin(),child.end());}
            alpha=std::max(alpha,score);if(alpha>=beta)break;
        }
        return best;
    }
};
}
SearchResult Search::run(Position root,const Limits& limits,const SearchOptions& options,std::shared_ptr<SearchControl> control,const InfoCallback& callback) {
    if(options.threads<1||options.threads>8||options.multipv<1||options.multipv>32||options.trace_limit<0||options.trace_limit>64||options.neural_weight<0||options.neural_weight>100||limits.depth<1||limits.depth>64)throw InputError("search resources out of bounds");
    auto start=monotonic_ns();control->initialize(limits);
    auto legal=root.legal();SearchResult result;
    auto state=rules(root,legal);if(state.ended()) {result.score=state.terminal==Termination::checkmate?-mate_score:0;return result;}
    if(!limits.root_moves.empty()) std::erase_if(legal,[&](Move m){return std::find(limits.root_moves.begin(),limits.root_moves.end(),m)==limits.root_moves.end();});
    if(legal.empty()) throw InputError("searchmoves contains no legal move");
    if(options.root_shuffle_seed) {
        std::mt19937_64 random(options.root_shuffle_seed^root.key());
        for(std::size_t remaining=legal.size();remaining>1;--remaining)
            std::swap(legal[remaining-1],legal[static_cast<std::size_t>(random()%remaining)]);
    }
    auto root_accumulator=options.network?options.network->refresh(root):Accumulator{};
    result.best=legal[0];result.score=evaluation_of(root,options,&root_accumulator);result.pv={result.best};
    table_->new_search();std::vector<std::unique_ptr<Worker>> workers;
    for(int i=0;i<options.threads;++i)workers.push_back(std::make_unique<Worker>(*table_,*control,options));
    std::vector<PrincipalLine> prior;
    for(auto m:legal)prior.push_back({m,0,{m},Bound::exact});
    for(int depth=1;depth<=limits.depth;++depth) {
        std::vector<PrincipalLine> current=prior;std::vector<unsigned char> completed(current.size(),0);std::atomic<std::size_t> next{0};std::atomic<int> root_alpha{-infinity};std::mutex error_mutex;std::exception_ptr worker_error;
        auto work=[&](int id) {
            auto& worker=*workers[static_cast<std::size_t>(id)];
            while(!control->stop.load(std::memory_order_relaxed)) {
                auto i=next.fetch_add(1,std::memory_order_relaxed);if(i>=current.size())break;
                try {
                    auto move=current[i].move;Position position=root;auto undo=position.make(move);(void)undo;worker.reset(position);
                    int alpha=-infinity,beta=infinity,window=25;Bound root_bound=Bound::exact;
                    int shared_alpha=root_alpha.load(std::memory_order_relaxed);int score=-infinity;Moves child;
                    bool screened=options.multipv==1&&options.pvs&&shared_alpha>-infinity;
                    if(screened) {
                        score=-worker.visit(position,depth-1,-shared_alpha-1,-shared_alpha,1,true,move,child);
                        if(score<=shared_alpha)root_bound=Bound::upper;
                    }
                    if(!screened||score>shared_alpha) {
                        if(options.aspiration&&depth>=4) {alpha=std::max(-infinity,prior[i].score-window);beta=std::min(infinity,prior[i].score+window);}
                        for(;;) {
                            score=-worker.visit(position,depth-1,-beta,-alpha,1,true,move,child);
                            if(score>alpha&&score<beta)break;
                            if(alpha==-infinity&&beta==infinity)break;
                            window*=2;alpha=std::max(-infinity,score-window);beta=std::min(infinity,score+window);
                            if(window>16000){alpha=-infinity;beta=infinity;}
                        }
                        int old=root_alpha.load(std::memory_order_relaxed);
                        while(old<score&&!root_alpha.compare_exchange_weak(old,score,std::memory_order_relaxed)){}
                    }
                    current[i]={move,score,{move},root_bound};current[i].pv.insert(current[i].pv.end(),child.begin(),child.end());completed[i]=1;
                }catch(const Abort&) {break;}
                catch(...) {std::lock_guard lock(error_mutex);if(!worker_error)worker_error=std::current_exception();control->stop.store(true);break;}
            }
        };
        if(options.threads==1)work(0);
        else {
            std::vector<JoiningThread> pool;
            try {
                for(int id=0;id<options.threads;++id) {
                    if(options.inject_worker_start_failure_after>=0&&id>=options.inject_worker_start_failure_after)throw std::runtime_error("injected worker startup failure");
                    pool.emplace_back(work,id);
                }
            }catch(...){control->stop.store(true);throw;}
        }
        if(worker_error)std::rethrow_exception(worker_error);
        bool complete=std::all_of(completed.begin(),completed.end(),[](auto v){return v!=0;});
        if(!complete) {result.interrupted=true;break;}
        std::stable_sort(current.begin(),current.end(),[](const auto& a,const auto& b){return a.score!=b.score?a.score>b.score:a.bound==Bound::exact&&b.bound!=Bound::exact;});prior=current;
        result.best=current[0].move;result.score=state.claimable()?std::max(0,current[0].score):current[0].score;result.pv=current[0].pv;
        SearchInfo info;info.depth=depth;info.nodes=control->nodes.load();info.completed_depth_nodes=info.nodes;info.elapsed_ms=(monotonic_ns()-start)/1000000;info.hashfull=table_->hashfull();
        for(auto& worker:workers)info.stats+=worker->stats;
        info.lines.assign(current.begin(),current.begin()+static_cast<std::ptrdiff_t>(std::min(current.size(),static_cast<std::size_t>(options.multipv))));result.info=info;
        if(callback)callback(info);
        if(control->stop.load()||monotonic_ns()>=control->deadline_ns.load())break;
    }
    result.info.nodes=control->nodes.load();if(limits.nodes)result.info.nodes=std::min(result.info.nodes,limits.nodes);
    result.info.elapsed_ms=(monotonic_ns()-start)/1000000;
    result.info.stats={};for(auto& worker:workers){result.info.stats+=worker->stats;result.info.trace.insert(result.info.trace.end(),worker->trace.begin(),worker->trace.end());}
    return result;
}
}
