#include "caissa/search_probe.hpp"
#include "caissa/search.hpp"
#include "caissa/protocol_io.hpp"
#include "caissa/serialization.hpp"
#include <charconv>
#include <iomanip>
#include <sstream>
namespace caissa {
namespace {
std::string hex(Key key){std::ostringstream out;out<<std::hex<<std::setw(16)<<std::setfill('0')<<key;return out.str();}
std::vector<std::string> words(std::string_view line) {
    std::istringstream input{std::string(line)};std::vector<std::string> result;
    for(std::string word;input>>word;){if(result.size()==70)throw InputError("search probe token ceiling");result.push_back(std::move(word));}
    return result;
}
int number(const std::string& text,int low,int high) {
    int value=0;auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),value);
    if(error!=std::errc{}||end!=text.data()+text.size()||value<low||value>high)throw InputError("search probe integer outside bounds");return value;
}
Key unsigned_number(const std::string& text,int base=10) {
    Key value=0;auto [end,error]=std::from_chars(text.data(),text.data()+text.size(),value,base);
    if(text.empty()||error!=std::errc{}||end!=text.data()+text.size())throw InputError("search probe unsigned integer malformed");return value;
}
class SearchProbe {
public:
    std::string command(std::string_view line) {
        if(line.starts_with("search "))return search(line);
        auto args=words(line);
        if(args.size()==1&&args[0]=="clear"){table_->clear();return "{\"operation\":\"clear\",\"bytes\":"+std::to_string(table_->bytes())+",\"hashfull\":"+std::to_string(table_->hashfull())+'}';}
        if(args.size()==1&&args[0]=="new"){table_->new_search();return "{\"operation\":\"new\"}";}
        if(args.size()<2||args[1].size()!=16)throw InputError("search probe key or command malformed");
        const auto key=unsigned_number(args[1],16);
        if(args[0]=="store"&&args.size()==10) {
            Move move{static_cast<Square>(number(args[2],0,63)),static_cast<Square>(number(args[3],0,63))};
            auto score=number(args[4],-30000,30000),evaluation=number(args[5],-28000,28000);
            auto depth=number(args[6],0,127),bound=number(args[7],1,3),ply=number(args[8],0,127);
            if(args[9]!="end")throw InputError("search probe store terminator differs");
            table_->store(key,move,score,evaluation,depth,static_cast<Bound>(bound),ply);
            return entry("store",key,ply);
        }
        if(args[0]=="hint"&&args.size()==5) {
            Move move{static_cast<Square>(number(args[2],0,63)),static_cast<Square>(number(args[3],0,63))};
            table_->store_hint(key,move,number(args[4],0,127));return entry("hint",key,0);
        }
        if(args[0]=="probe"&&args.size()==3)return entry("probe",key,number(args[2],0,127));
        throw InputError("unsupported search probe command");
    }
private:
    std::shared_ptr<TranspositionTable> table_=std::make_shared<TranspositionTable>(1);
    std::string entry(std::string_view operation,Key key,int ply) {
        auto found=table_->probe(key);auto hint=table_->ordering_hint(key);std::ostringstream out;
        out<<"{\"operation\":"<<json_quote(operation)<<",\"query_key\":"<<json_quote(hex(key))<<",\"query_ply\":"<<ply<<",\"entry\":";
        if(!found)out<<"null";
        else out<<"{\"key\":"<<json_quote(hex(found->key))<<",\"move\":"<<found->move.packed()<<",\"stored_score\":"<<found->score<<",\"score\":"<<mate_from_table(found->score,ply)<<",\"evaluation\":"<<found->evaluation<<",\"depth\":"<<found->depth<<",\"bound\":"<<unsigned(found->bound)<<",\"age\":"<<unsigned(found->age)<<'}';
        out<<",\"hint\":";if(hint)out<<hint->packed();else out<<"null";out<<'}';return out.str();
    }
    std::string search(std::string_view line) {
        auto split=line.find('|');if(split==std::string_view::npos)throw InputError("search probe requires FEN delimiter");
        auto args=words(line.substr(0,split));if(args.size()!=6)throw InputError("search probe header differs");
        auto depth=number(args[1],1,6),flags=number(args[2],0,8191);auto seed=unsigned_number(args[3]);
        auto nodes=number(args[4],1,500000);bool c960=number(args[5],0,1)!=0;
        line.remove_prefix(split+1);split=line.find('|');if(split==std::string_view::npos)throw InputError("search probe requires history delimiter");
        auto position=Position::from_fen(line.substr(0,split),c960);auto history=words(line.substr(split+1));
        if(history.size()>64)throw InputError("search probe history ceiling");
        for(const auto& text:history){auto move=position.parse_uci(text);if(!move)throw InputError("search probe illegal history");position.make(*move);}
        SearchOptions options;options.table=flags&1;options.pvs=flags&2;options.aspiration=flags&4;
        options.ordering_hints=flags&8;options.lmr=flags&16;options.null_move=flags&32;options.quiescence=flags&64;
        options.extensions=flags&128;options.history=flags&256;options.see=flags&512;options.futility=flags&1024;
        options.evaluation_cache=flags&2048;options.tactical_generation=flags&4096;options.root_shuffle_seed=seed;
        Limits limits;limits.depth=depth;limits.nodes=static_cast<std::uint64_t>(nodes);
        Search engine(table_);auto result=engine.run(position,limits,options,std::make_shared<SearchControl>());
        auto terminal=rules(position);std::ostringstream out;
        out<<"{\"operation\":\"search\",\"fen\":"<<json_quote(position.fen())<<",\"chess960\":"<<(c960?"true":"false")<<",\"key\":"<<json_quote(hex(position.key()))
           <<",\"search_key\":"<<json_quote(hex(position.search_key()))<<",\"flags\":"<<flags<<",\"seed\":"<<seed<<",\"requested_depth\":"<<depth
           <<",\"node_limit\":"<<nodes<<",\"terminal\":"<<json_quote(termination_name(terminal.terminal))<<",\"score\":"<<result.score
           <<",\"depth\":"<<result.info.depth<<",\"nodes\":"<<result.info.nodes<<",\"interrupted\":"<<(result.interrupted?"true":"false")
           <<",\"bestmove\":"<<json_quote(result.best.valid()?position.uci(result.best):"0000")<<",\"pv\":[";
        auto replay=position;for(std::size_t i=0;i<result.pv.size();++i){if(i)out<<',';out<<json_quote(replay.uci(result.pv[i]));replay.make(result.pv[i]);}
        const auto& s=result.info.stats;
        out<<"],\"stats\":{\"table_hits\":"<<s.table_hits<<",\"table_cutoffs\":"<<s.table_cutoffs<<",\"beta_cutoffs\":"<<s.beta_cutoffs
           <<",\"qnodes\":"<<s.qnodes<<",\"null_cutoffs\":"<<s.null_cutoffs<<",\"lmr_searches\":"<<s.lmr_searches<<",\"researches\":"<<s.researches
           <<",\"futility_skips\":"<<s.futility_skips<<",\"ordering_hint_hits\":"<<s.ordering_hint_hits<<",\"evaluation_cache_hits\":"<<s.evaluation_cache_hits
           <<",\"evaluator_calls\":"<<s.evaluator_calls<<",\"neural_evaluations\":"<<s.neural_evaluations<<"}}";return out.str();
    }
};
}
int search_probe(std::istream& input,std::ostream& output) {
    ProtocolOutput channel(output);SearchProbe probe;std::string line;bool overlong=false;unsigned requests=0;
    read_protocol_input(input,[&](char ch){
        if(ch!='\n'){if(line.size()<1024&&!overlong)line+=ch;else overlong=true;return true;}
        if(++requests>10000){channel.send("{\"error\":\"search probe request ceiling\"}");return false;}
        try {
            if(overlong||line.find('\0')!=std::string::npos||line.find('\r')!=std::string::npos)throw InputError("search probe byte ceiling or delimiter");
            channel.send(probe.command(line));
        }catch(const InputError& error){channel.send("{\"error\":"+json_quote(error.what())+'}');}
        line.clear();overlong=false;return !channel.failed();
    },[&]{return channel.failed();});return channel.finish()?0:1;
}
}
