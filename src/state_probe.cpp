#include "caissa/state_probe.hpp"
#include "caissa/accumulator_stack.hpp"
#include "caissa/evaluation.hpp"
#include "caissa/protocol_io.hpp"
#include "caissa/rules.hpp"
#include "caissa/serialization.hpp"
#include <algorithm>
#include <iomanip>
#include <sstream>
namespace caissa {
namespace {
std::string hex(Key key) {
    std::ostringstream out;out<<std::hex<<std::setw(16)<<std::setfill('0')<<key;return out.str();
}
class StateProbe {
public:
    explicit StateProbe(const Network& network):network_(network),accumulator_(network,true) {
        undos_.reserve(max_ply);accumulator_.reset(position_);
    }
    std::string command(std::string_view line) {
        if(line=="rules")return rule_state();
        if(line.starts_with("reset ")) {
            auto fen=line.substr(6);bool c960=fen.starts_with("960|");if(c960)fen.remove_prefix(4);
            auto next=Position::from_fen(fen,c960);position_=std::move(next);
            undos_.clear();accumulator_.reset(position_);
        }else if(line=="undo") {
            if(undos_.empty())throw InputError("state probe undo at root");
            position_.unmake(undos_.back());undos_.pop_back();accumulator_.pop();
        }else if(line.starts_with("move ")||line=="null") {
            if(undos_.size()+1>=max_ply)throw InputError("state probe depth ceiling");
            Undo undo;
            if(line=="null") {
                if(position_.in_check(position_.side()))throw InputError("state probe null while checked");
                undo=position_.make_null();
            }else {
                auto move=position_.parse_uci(line.substr(5));
                if(!move)throw InputError("state probe illegal move");
                undo=position_.make(*move);
            }
            try{accumulator_.push(position_,undo);}catch(...){position_.unmake(undo);throw;}
            undos_.push_back(undo);
        }else if(line!="state")throw InputError("unsupported state probe command");
        return state();
    }
private:
    const Network& network_;Position position_=Position::start();
    AccumulatorStack accumulator_;std::vector<Undo> undos_;
    std::string rule_state() {
        const auto fen=position_.fen();const std::vector<Key> history(position_.history().begin(),position_.history().end());
        const auto key=position_.key(),search=position_.search_key();
        const auto legal=position_.legal();const auto availability=position_.availability();
        const auto direct=rules(position_),listed=rules(position_,legal),available=rules(position_,availability);
        auto equal=[](const RuleState& a,const RuleState& b){return a.terminal==b.terminal&&a.threefold_claim==b.threefold_claim&&a.fifty_move_claim==b.fifty_move_claim;};
        std::vector<std::string> claims;
        for(auto move:claim_by_move(position_))claims.push_back(position_.uci(move));
        std::sort(claims.begin(),claims.end());
        const bool restored=position_.fen()==fen&&std::equal(history.begin(),history.end(),position_.history().begin(),position_.history().end())&&position_.key()==key&&position_.search_key()==search&&position_.coherent();
        std::ostringstream out;
        out<<"{\"fen\":"<<json_quote(fen)<<",\"chess960\":"<<(position_.chess960()?"true":"false")
           <<",\"terminal\":"<<json_quote(termination_name(direct.terminal))
           <<",\"threefold_claim\":"<<(direct.threefold_claim?"true":"false")
           <<",\"fifty_move_claim\":"<<(direct.fifty_move_claim?"true":"false")
           <<",\"ended\":"<<(direct.ended()?"true":"false")<<",\"claimable\":"<<(direct.claimable()?"true":"false")
           <<",\"proven_dead\":"<<(proven_dead(position_)?"true":"false")
           <<",\"synthetic_depth\":"<<position_.synthetic_depth()<<",\"repetitions\":"<<position_.repetitions()
           <<",\"key\":"<<json_quote(hex(key))<<",\"repetition_key\":"<<json_quote(hex(position_.repetition_key()))
           <<",\"search_key\":"<<json_quote(hex(search))
           <<",\"overloads_equal\":"<<(equal(direct,listed)&&equal(direct,available)?"true":"false")
           <<",\"restored\":"<<(restored?"true":"false")<<",\"claim_moves\":[";
        for(std::size_t i=0;i<claims.size();++i){if(i)out<<',';out<<json_quote(claims[i]);}
        out<<"]}";return out.str();
    }
    std::string state() {
        const auto& accumulator=accumulator_.get(position_);auto refreshed=network_.refresh(position_);
        std::ostringstream out;
        out<<"{\"fen\":"<<json_quote(position_.fen())<<",\"chess960\":"<<(position_.chess960()?"true":"false")
           <<",\"key\":"<<json_quote(hex(position_.key()))<<",\"recomputed_key\":"<<json_quote(hex(position_.recompute_key()))
           <<",\"repetition_key\":"<<json_quote(hex(position_.repetition_key()))<<",\"search_key\":"<<json_quote(hex(position_.search_key()))
           <<",\"synthetic_depth\":"<<position_.synthetic_depth()<<",\"halfmove\":"<<position_.halfmove()
           <<",\"fullmove\":"<<position_.fullmove()<<",\"side\":"<<index(position_.side())<<",\"ep\":"<<unsigned(position_.ep())
           <<",\"depth\":"<<undos_.size()<<",\"coherent\":"<<(position_.coherent()?"true":"false")<<",\"board\":[";
        for(Square s=0;s<64;++s){if(s)out<<',';out<<unsigned(position_.at(s));}
        out<<"],\"rights\":[";
        for(Color c:{Color::white,Color::black}) {
            if(c==Color::black)out<<',';
            out<<'['<<unsigned(position_.rook_right(c,0))<<','<<unsigned(position_.rook_right(c,1))<<']';
        }
        out<<"],\"occupied\":["<<json_quote(hex(position_.occupied(Color::white)))<<','<<json_quote(hex(position_.occupied(Color::black)))
           <<"],\"bitboards\":[";
        for(Color c:{Color::white,Color::black}) {
            if(c==Color::black)out<<',';out<<'[';
            for(int k=0;k<7;++k){if(k)out<<',';out<<json_quote(hex(position_.pieces(c,static_cast<Kind>(k))));}
            out<<']';
        }
        out<<"],\"history\":[";bool first=true;
        for(auto key:position_.history()){if(!first)out<<',';first=false;out<<json_quote(hex(key));}
        out<<"],\"repetitions\":"<<position_.repetitions()<<",\"accumulator\":[";
        for(std::size_t c=0;c<2;++c) {
            if(c)out<<',';out<<'[';
            for(std::size_t i=0;i<transformer_width;++i){if(i)out<<',';out<<accumulator.values[c][i];}
            out<<']';
        }
        out<<"],\"buckets\":["<<accumulator.buckets[0]<<','<<accumulator.buckets[1]<<"],\"accumulator_key\":"<<json_quote(hex(accumulator.position_key))
           <<",\"full_refresh_equal\":"<<(accumulator==refreshed?"true":"false")
           <<",\"baseline\":"<<classical(position_)<<",\"scalar\":"<<network_.evaluate(position_,accumulator,true,10)
           <<",\"native\":"<<network_.evaluate(position_,accumulator,false,10)
           <<",\"refreshed\":"<<network_.evaluate(position_,refreshed,true,10)<<'}';
        return out.str();
    }
};
}
int state_probe(std::istream& input,std::ostream& output,const Network& network) {
    ProtocolOutput channel(output);StateProbe probe(network);std::string line;bool overlong=false;
    std::uint64_t commands=0;
    read_protocol_input(input,[&](char ch) {
        if(ch!='\n') {
            if(line.size()<1024&&!overlong)line+=ch;else overlong=true;
            return true;
        }
        if(++commands>10000000){channel.send("{\"error\":\"state probe command ceiling\"}");return false;}
        try {
            if(overlong||line.find('\0')!=std::string::npos||line.find('\r')!=std::string::npos)
                throw InputError("state probe command byte ceiling or delimiter");
            channel.send(probe.command(line));
        }catch(const InputError& error){channel.send("{\"error\":"+json_quote(error.what())+'}');}
        line.clear();overlong=false;return !channel.failed();
    },[&]{return channel.failed();});
    return channel.finish()?0:1;
}
}
