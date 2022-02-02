#include "caissa/search.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <thread>
namespace caissa {
std::int64_t monotonic_ns() {return std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
void SearchControl::ponderhit() {
    pondering.store(false,std::memory_order_release);
    if(ponder_budget_ms>0) deadline_ns.store(monotonic_ns()+ponder_budget_ms*1000000,std::memory_order_relaxed);
}
std::int64_t time_budget(std::int64_t remaining,std::int64_t increment,int moves_to_go,int overhead) {
    auto available=std::max<std::int64_t>(1,remaining-overhead);
    auto allocation=available/std::clamp(moves_to_go,1,60)+increment*3/4;
    return std::clamp<std::int64_t>(allocation,1,std::max<std::int64_t>(1,available/2));
}
SearchStats& SearchStats::operator+=(const SearchStats& r) {
    qnodes+=r.qnodes;table_hits+=r.table_hits;table_cutoffs+=r.table_cutoffs;beta_cutoffs+=r.beta_cutoffs;
    null_cutoffs+=r.null_cutoffs;lmr_searches+=r.lmr_searches;researches+=r.researches;futility_skips+=r.futility_skips;
    evaluator_calls+=r.evaluator_calls;evaluator_ns+=r.evaluator_ns;seldepth=std::max(seldepth,r.seldepth);return *this;
}
namespace {
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
    Worker(TranspositionTable& table,SearchControl& control,const SearchOptions& options):table_(table),control_(control),options_(options){}
    SearchStats stats;
    void reset(const Position& p){if(options_.network)accumulator_=options_.network->refresh(p);}
    int visit(Position& p,int depth,int alpha,int beta,int ply,bool allow_null,Move previous,Moves& pv) {
        touch(ply);pv.clear();
        if(ply>=max_ply-1) return evaluate(p);
        bool check=p.in_check(p.side());
        auto moves=p.legal();auto state=rules(p,moves);
        if(state.ended()) return state.terminal==Termination::checkmate?-mate_score+ply:0;
        bool claim=state.claimable();
        if(claim) {if(beta<=0)return 0;alpha=std::max(alpha,0);}
        if(depth<=0) {
            if(!options_.quiescence) return std::max(claim?0:-infinity,evaluate(p));
            return quiet(p,alpha,beta,ply,0,claim,std::move(moves),pv);
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
        if(options_.table) table_.store(key,bestmove,best,evaluation,depth,best>=beta?Bound::lower:best<=original_alpha?Bound::upper:Bound::exact,ply);
        return best;
    }
private:
    TranspositionTable& table_;SearchControl& control_;const SearchOptions& options_;
    std::array<std::array<Move,2>,max_ply> killers_{};
    std::array<std::array<Move,64>,64> counters_{};
    std::array<std::array<std::array<int,64>,64>,2> history_{};
    std::uint64_t local_nodes_=0;Accumulator accumulator_;
    void touch(int ply) {
        if(control_.stop.load(std::memory_order_relaxed)) throw Abort{};
        auto ticket=control_.nodes.fetch_add(1,std::memory_order_relaxed);
        if(control_.node_limit&&ticket>=control_.node_limit) {control_.stop.store(true,std::memory_order_relaxed);throw Abort{};}
        if((++local_nodes_&63U)==0&&monotonic_ns()>=control_.deadline_ns.load(std::memory_order_relaxed)) {control_.stop.store(true,std::memory_order_relaxed);throw Abort{};}
        stats.seldepth=std::max(stats.seldepth,ply);
    }
    int evaluate(const Position& p) {
        auto begin=monotonic_ns();int score=options_.network?options_.network->evaluate(p,accumulator_,options_.scalar_network):classical(p);++stats.evaluator_calls;
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
    int quiet(Position& p,int alpha,int beta,int ply,int qply,bool claim,Moves moves,Moves& pv) {
        ++stats.qnodes;bool check=p.in_check(p.side());
        int best=claim?0:-infinity;
        if(!check) {best=std::max(best,evaluate(p));if(best>=beta)return best;alpha=std::max(alpha,best);}
        if(qply>=24||ply>=max_ply-2) return check?evaluate(p):best;
        order(p,moves,{}, {},ply);
        for(auto m:moves) {
            if(!check&&!is_capture(p,m)&&m.promotion==Kind::none)continue;
            Moves child;int score;
            {Guard guard(p,m,options_.network.get(),options_.network?&accumulator_:nullptr);touch(ply+1);auto replies=p.legal();auto state=rules(p,replies);
                if(state.ended()) score=state.terminal==Termination::checkmate?mate_score-ply-1:0;
                else score=-quiet(p,-beta,-alpha,ply+1,qply+1,state.claimable(),std::move(replies),child);
            }
            if(score>best) {best=score;pv={m};pv.insert(pv.end(),child.begin(),child.end());}
            alpha=std::max(alpha,score);if(alpha>=beta)break;
        }
        return best;
    }
};
}
SearchResult Search::run(Position root,const Limits& limits,const SearchOptions& options,std::shared_ptr<SearchControl> control,const InfoCallback& callback) {
    if(options.threads<1||options.threads>8||options.multipv<1||options.multipv>32||limits.depth<1||limits.depth>64)throw InputError("search resources out of bounds");
    auto start=monotonic_ns();control->node_limit=limits.nodes;control->ponder_budget_ms=limits.milliseconds;control->pondering.store(limits.ponder);
    if(limits.milliseconds>0&&!limits.ponder&&!limits.infinite)control->deadline_ns.store(start+limits.milliseconds*1000000);
    auto legal=root.legal();SearchResult result;
    auto state=rules(root,legal);if(state.ended()) {result.score=state.terminal==Termination::checkmate?-mate_score:0;return result;}
    if(!limits.root_moves.empty()) std::erase_if(legal,[&](Move m){return std::find(limits.root_moves.begin(),limits.root_moves.end(),m)==limits.root_moves.end();});
    if(legal.empty()) throw InputError("searchmoves contains no legal move");
    result.best=legal[0];result.score=options.network?options.network->evaluate(root,options.network->refresh(root),options.scalar_network):classical(root);result.pv={result.best};
    table_->new_search();std::vector<std::unique_ptr<Worker>> workers;
    for(int i=0;i<options.threads;++i)workers.push_back(std::make_unique<Worker>(*table_,*control,options));
    std::vector<PrincipalLine> prior;
    for(auto m:legal)prior.push_back({m,0,{m},Bound::exact});
    for(int depth=1;depth<=limits.depth;++depth) {
        std::vector<PrincipalLine> current=prior;std::vector<unsigned char> completed(current.size(),0);std::atomic<std::size_t> next{0};
        auto work=[&](int id) {
            auto& worker=*workers[static_cast<std::size_t>(id)];
            while(!control->stop.load(std::memory_order_relaxed)) {
                auto i=next.fetch_add(1,std::memory_order_relaxed);if(i>=current.size())break;
                auto move=current[i].move;Position position=root;auto undo=position.make(move);(void)undo;worker.reset(position);
                try {
                    int alpha=-infinity,beta=infinity,window=25;
                    if(options.aspiration&&depth>=4) {alpha=std::max(-infinity,prior[i].score-window);beta=std::min(infinity,prior[i].score+window);}
                    int score;Moves child;
                    for(;;) {
                        score=-worker.visit(position,depth-1,-beta,-alpha,1,true,move,child);
                        if(score>alpha&&score<beta)break;
                        if(alpha==-infinity&&beta==infinity)break;
                        window*=2;alpha=std::max(-infinity,score-window);beta=std::min(infinity,score+window);
                        if(window>16000){alpha=-infinity;beta=infinity;}
                    }
                    current[i]={move,score,{move},Bound::exact};current[i].pv.insert(current[i].pv.end(),child.begin(),child.end());completed[i]=1;
                }catch(const Abort&) {break;}
            }
        };
        if(options.threads==1)work(0);
        else {std::vector<std::jthread> pool;for(int id=0;id<options.threads;++id)pool.emplace_back(work,id);}
        bool complete=std::all_of(completed.begin(),completed.end(),[](auto v){return v!=0;});
        if(!complete) {result.interrupted=true;break;}
        std::stable_sort(current.begin(),current.end(),[](const auto& a,const auto& b){return a.score>b.score;});prior=current;
        result.best=current[0].move;result.score=state.claimable()?std::max(0,current[0].score):current[0].score;result.pv=current[0].pv;
        SearchInfo info;info.depth=depth;info.nodes=control->nodes.load();info.elapsed_ms=(monotonic_ns()-start)/1000000;info.hashfull=table_->hashfull();
        for(auto& worker:workers)info.stats+=worker->stats;
        info.lines.assign(current.begin(),current.begin()+static_cast<std::ptrdiff_t>(std::min(current.size(),static_cast<std::size_t>(options.multipv))));result.info=info;
        if(callback)callback(info);
        if(control->stop.load()||monotonic_ns()>=control->deadline_ns.load())break;
    }
    result.info.nodes=control->nodes.load();if(limits.nodes)result.info.nodes=std::min(result.info.nodes,limits.nodes);
    result.info.elapsed_ms=(monotonic_ns()-start)/1000000;
    result.info.stats={};for(auto& worker:workers)result.info.stats+=worker->stats;
    return result;
}
}
