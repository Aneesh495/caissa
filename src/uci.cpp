#include "caissa/uci.hpp"
#include "caissa/search.hpp"
#include "caissa/version.hpp"
#include <charconv>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>
namespace caissa {
namespace {
std::vector<std::string> tokens(std::string_view line) {
    std::vector<std::string> out;std::istringstream stream{std::string(line)};std::string s;
    while(stream>>s) {if(out.size()>=2048)throw InputError("too many command tokens");out.push_back(s);}return out;
}
std::uint64_t number(std::string_view s,std::uint64_t maximum=1000000000000ULL) {
    std::uint64_t value=0;auto [p,e]=std::from_chars(s.data(),s.data()+s.size(),value);
    if(e!=std::errc{}||p!=s.data()+s.size()||value>maximum)throw InputError("invalid or oversized integer");return value;
}
bool boolean(const std::string& s) {if(s=="true")return true;if(s=="false")return false;throw InputError("boolean must be true or false");}
class Session {
public:
    explicit Session(std::ostream& output):output_(output),position_(Position::start()),table_(std::make_shared<TranspositionTable>(32)){}
    ~Session(){stop();}
    bool command(const std::string& line) {
        auto t=tokens(line);if(t.empty())return true;auto& cmd=t[0];
        if(cmd=="quit") {stop();return false;}
        if(cmd=="uci") {
            emit("id name "+std::string(version()));emit("id author Aneesh Krishna");
            emit("option name Hash type spin default 32 min 1 max 1024");
            emit("option name Threads type spin default 1 min 1 max 8");
            emit("option name MultiPV type spin default 1 min 1 max 32");
            emit("option name Move Overhead type spin default 20 min 0 max 1000");
            emit("option name UCI_Chess960 type check default false");emit("option name Ponder type check default false");
            for(auto name:{"Null Move","LMR","Extensions","PVS","Aspiration","Quiescence","History","SEE","Futility","Use Table"})emit(std::string("option name ")+name+" type check default true");
            emit("option name EvalFile type string default <empty>");emit("option name Use Neural type check default false");emit("option name Scalar Neural type check default false");
            emit("option name Search Stats type check default false");emit("option name Trace Samples type spin default 0 min 0 max 64");
            emit("option name Clear Hash type button");emit("uciok");
        } else if(cmd=="isready") emit("readyok");
        else if(cmd=="stop") stop();
        else if(cmd=="ponderhit") {if(control_)control_->ponderhit();}
        else if(cmd=="ucinewgame") {stop();table_->clear();position_=Position::from_fen(start_fen,chess960_);}
        else if(cmd=="setoption") option(t);
        else if(cmd=="position") set_position(t);
        else if(cmd=="go") go(t);
        else if(cmd=="d") emit("info string fen "+position_.fen());
        else if(cmd=="eval") emit("info string classical cp "+std::to_string(classical(position_)));
        else if(cmd=="debug"||cmd=="register") emit("info string command acknowledged");
        else throw InputError("unsupported command");
        return true;
    }
    void error(const std::exception& e){emit("info string error "+std::string(e.what()));}
private:
    std::ostream& output_;std::mutex output_mutex_;Position position_;
    std::shared_ptr<TranspositionTable> table_;SearchOptions options_;
    std::shared_ptr<SearchControl> control_;std::jthread worker_;
    int overhead_=20;bool chess960_=false,inspect_stats_=false;std::shared_ptr<const Network> loaded_network_;
    void emit(const std::string& text){std::lock_guard lock(output_mutex_);output_<<text<<'\n'<<std::flush;}
    void stop(){if(control_)control_->stop.store(true);if(worker_.joinable())worker_.join();control_.reset();}
    void option(const std::vector<std::string>& t) {
        if(t.size()<3||t[1]!="name")throw InputError("setoption requires name");
        std::string name,value;std::size_t i=2;
        for(;i<t.size()&&t[i]!="value";++i){if(!name.empty())name+=' ';name+=t[i];}
        if(i<t.size()) for(++i;i<t.size();++i){if(!value.empty())value+=' ';value+=t[i];}
        stop();
        if(name=="Clear Hash"){table_->clear();return;}
        if(name=="EvalFile") {loaded_network_=Network::load(value);if(options_.network)options_.network=loaded_network_;emit("info string network "+loaded_network_->identity());}
        else if(name=="Use Neural") {bool use=boolean(value);if(use&&!loaded_network_)throw InputError("load EvalFile before enabling neural evaluation");options_.network=use?loaded_network_:nullptr;}
        else if(name=="Scalar Neural") options_.scalar_network=boolean(value);
        else if(name=="Hash")table_=std::make_shared<TranspositionTable>(static_cast<std::size_t>(number(value,1024)));
        else if(name=="Threads"){auto n=number(value,8);if(n==0)throw InputError("Threads must be positive");options_.threads=static_cast<int>(n);}
        else if(name=="MultiPV"){auto n=number(value,32);if(n==0)throw InputError("MultiPV must be positive");options_.multipv=static_cast<int>(n);}
        else if(name=="Search Stats")inspect_stats_=boolean(value);
        else if(name=="Trace Samples")options_.trace_limit=static_cast<int>(number(value,64));
        else if(name=="Move Overhead")overhead_=static_cast<int>(number(value,1000));
        else if(name=="UCI_Chess960")chess960_=boolean(value);
        else if(name=="Ponder") {(void)boolean(value);}
        else {
            bool v=boolean(value);
            if(name=="Null Move")options_.null_move=v;else if(name=="LMR")options_.lmr=v;
            else if(name=="Extensions")options_.extensions=v;else if(name=="PVS")options_.pvs=v;
            else if(name=="Aspiration")options_.aspiration=v;else if(name=="Quiescence")options_.quiescence=v;
            else if(name=="History")options_.history=v;else if(name=="SEE")options_.see=v;
            else if(name=="Futility")options_.futility=v;else if(name=="Use Table")options_.table=v;
            else throw InputError("unknown option");
        }
        table_->clear();
    }
    void set_position(const std::vector<std::string>& t) {
        if(t.size()<2)throw InputError("position missing specification");
        std::size_t i=2;Position next=Position::start();
        if(t[1]=="startpos")next=Position::from_fen(start_fen,chess960_);
        else if(t[1]=="fen") {
            if(t.size()<8)throw InputError("position FEN needs six fields");
            std::string fen;for(;i<8;++i){if(!fen.empty())fen+=' ';fen+=t[i];}next=Position::from_fen(fen,chess960_);
        } else throw InputError("expected startpos or fen");
        if(i<t.size()) {
            if(t[i++]!="moves")throw InputError("expected moves");
            if(t.size()-i>1024)throw InputError("position history exceeds 1024 plies");
            for(;i<t.size();++i){auto m=next.parse_uci(t[i]);if(!m)throw InputError("illegal position move");next.make(*m);}
        }
        stop();position_=std::move(next);
    }
    void info(const Position& root,const SearchInfo& info) {
        for(std::size_t i=0;i<info.lines.size();++i) {
            auto& line=info.lines[i];std::ostringstream text;
            text<<"info depth "<<info.depth<<" seldepth "<<info.stats.seldepth<<" multipv "<<i+1<<" score ";
            if(std::abs(line.score)>=mate_threshold)text<<"mate "<<(line.score>0?(mate_score-line.score+1)/2:-(mate_score+line.score+1)/2);
            else text<<"cp "<<line.score;
            if(line.bound==Bound::lower)text<<" lowerbound";else if(line.bound==Bound::upper)text<<" upperbound";
            text<<" nodes "<<info.nodes<<" time "<<info.elapsed_ms<<" nps "<<info.nodes*1000/static_cast<std::uint64_t>(std::max<std::int64_t>(1,info.elapsed_ms))<<" hashfull "<<info.hashfull<<" pv";
            auto p=root;for(auto m:line.pv){text<<' '<<p.uci(m);p.make(m);}emit(text.str());
        }
    }
    void go(const std::vector<std::string>& t) {
        Limits limits;std::uint64_t wtime=0,btime=0,winc=0,binc=0;int moves_to_go=30;bool have_clock=false,have_limit=false;
        for(std::size_t i=1;i<t.size();++i) {
            auto& word=t[i];
            if(word=="infinite"){limits.infinite=true;have_limit=true;continue;}
            if(word=="ponder"){limits.ponder=true;continue;}
            if(word=="searchmoves") {
                while(i+1<t.size()) {auto move=position_.parse_uci(t[i+1]);if(!move)break;limits.root_moves.push_back(*move);++i;}
                if(limits.root_moves.empty())throw InputError("searchmoves missing legal moves");continue;
            }
            if(i+1>=t.size())throw InputError("go field missing value");auto value=number(t[++i]);
            if(word=="depth"){if(value<1||value>64)throw InputError("depth outside [1,64]");limits.depth=static_cast<int>(value);have_limit=true;}
            else if(word=="nodes"){if(value==0)throw InputError("nodes must be positive");limits.nodes=value;have_limit=true;}
            else if(word=="movetime"){limits.milliseconds=static_cast<std::int64_t>(std::clamp<std::uint64_t>(value,1,600000));have_limit=true;}
            else if(word=="wtime"){wtime=value;have_clock=true;}else if(word=="btime"){btime=value;have_clock=true;}
            else if(word=="winc")winc=value;else if(word=="binc")binc=value;
            else if(word=="movestogo"){if(value<1||value>1000)throw InputError("invalid movestogo");moves_to_go=static_cast<int>(value);}
            else if(word=="mate"){if(value<1||value>32)throw InputError("mate outside [1,32]");limits.depth=static_cast<int>(2*value);have_limit=true;}
            else throw InputError("unknown go field");
        }
        if(have_clock&&limits.milliseconds==0) {
            auto remaining=position_.side()==Color::white?wtime:btime,increment=position_.side()==Color::white?winc:binc;
            limits.milliseconds=time_budget(static_cast<std::int64_t>(remaining),static_cast<std::int64_t>(increment),moves_to_go,overhead_);
            limits.milliseconds=std::min<std::int64_t>(limits.milliseconds,600000);
        } else if(!have_clock&&!have_limit)limits.milliseconds=1000;
        stop();control_=std::make_shared<SearchControl>();control_->initialize(limits);auto control=control_;auto root=position_;auto options=options_;auto table=table_;bool stats_enabled=inspect_stats_;
        worker_=std::jthread([this,control,root,options,table,limits,stats_enabled] {
            try {
                Search search(table);auto result=search.run(root,limits,options,control,[&](const SearchInfo& data){info(root,data);});
                while(control->pondering.load()&&!control->stop.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
                if(stats_enabled) {
                    auto& s=result.info.stats;std::ostringstream details;
                    details<<"info string stats qnodes "<<s.qnodes<<" tt_hits "<<s.table_hits<<" tt_cutoffs "<<s.table_cutoffs<<" beta_cutoffs "<<s.beta_cutoffs<<" null_cutoffs "<<s.null_cutoffs<<" lmr "<<s.lmr_searches<<" researches "<<s.researches<<" futility "<<s.futility_skips<<" eval_calls "<<s.evaluator_calls<<" eval_ns "<<s.evaluator_ns<<" completed_depth_nodes "<<result.info.completed_depth_nodes;emit(details.str());
                }
                for(auto& sample:result.info.trace) {
                    std::ostringstream detail;detail<<"info string trace depth "<<sample.depth<<" ply "<<sample.ply<<" alpha "<<sample.alpha<<" beta "<<sample.beta<<" synthetic "<<sample.synthetic<<" fen "<<sample.fen;emit(detail.str());
                }
                std::string text="bestmove "+root.uci(result.best);
                if(result.pv.size()>1){auto next=root;next.make(result.best);text+=" ponder "+next.uci(result.pv[1]);}emit(text);
            }catch(const std::exception& e){error(e);auto p=root;auto moves=p.legal();emit("bestmove "+(moves.empty()?std::string("0000"):p.uci(moves[0])));}
        });
    }
};
}
int uci_loop(std::istream& input,std::ostream& output) {
    Session session(output);std::string line;line.reserve(8192);bool oversized=false;char c;
    while(input.get(c)) {
        if(c!='\n') {if(line.size()<8192)line+=c;else oversized=true;continue;}
        if(oversized){InputError e("command exceeds 8192 bytes");session.error(e);}
        else try{if(!session.command(line))return 0;}catch(const std::exception& e){session.error(e);}
        line.clear();oversized=false;
    }
    if(!line.empty()&&!oversized)try{session.command(line);}catch(const std::exception& e){session.error(e);}
    return 0;
}
}
