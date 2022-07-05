#include "caissa/network.hpp"
#include "caissa/search.hpp"
#include "caissa/reference.hpp"
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <unistd.h>

using namespace caissa;
namespace {
std::uint64_t visited=0;
void check(bool value,const char* message) {
    if(!value)throw std::runtime_error(message);
}
int exact_evaluation(const Network& net,const Position& position,int weight) {
    return net.evaluate(position,net.refresh(position),true,weight);
}
int full_quiet(Position& p,const Network& net,int weight,int ply,int qply) {
    if(++visited>1000000)throw std::runtime_error("independent tree exceeded its explicit workload cap");
    auto moves=reference::legal(p);
    auto state=rules(p,moves);
    if(state.ended())return state.terminal==Termination::checkmate?-mate_score+ply:0;
    bool checked=p.in_check(p.side());
    int best=state.claimable()?0:-infinity;
    int evaluation=exact_evaluation(net,p,weight);
    if(!checked)best=std::max(best,evaluation);
    if(qply>=24||ply>=max_ply-2)return checked?evaluation:best;
    for(auto move:moves) {
        bool capture=move.flag==MoveFlag::en_passant||(move.flag!=MoveFlag::castle&&p.at(move.to));
        if(!checked&&!capture&&move.promotion==Kind::none)continue;
        auto undo=p.make(move);
        int score=-full_quiet(p,net,weight,ply+1,qply+1);
        p.unmake(undo);
        best=std::max(best,score);
    }
    return best;
}
int full_tree(Position& p,const Network& net,int weight,int depth,int ply) {
    auto moves=reference::legal(p);
    auto state=rules(p,moves);
    if(state.ended())return state.terminal==Termination::checkmate?-mate_score+ply:0;
    if(depth==0)return full_quiet(p,net,weight,ply,0);
    int best=state.claimable()?0:-infinity;
    for(auto move:moves) {
        auto undo=p.make(move);
        int score=-full_tree(p,net,weight,depth-1,ply+1);
        p.unmake(undo);
        best=std::max(best,score);
    }
    return best;
}
struct TemporaryNetwork {
    std::filesystem::path path=std::filesystem::temp_directory_path()/
        ("caissa-bound-"+std::to_string(getpid())+"-"+std::to_string(monotonic_ns())+".cai");
    ~TemporaryNetwork(){std::error_code error;std::filesystem::remove(path,error);}
    std::shared_ptr<const Network> make() {
        constexpr std::size_t payload=feature_count*transformer_width*2+transformer_width*4+
            dense1_width*transformer_width*4+dense1_width*4+dense2_width*dense1_width*2+
            dense2_width*4+dense2_width*2+4;
        std::vector<std::uint8_t> bytes(120+payload,0);
        auto put=[&](std::size_t at,std::uint32_t value) {
            for(int byte=0;byte<4;++byte)bytes[at+static_cast<std::size_t>(byte)]=static_cast<std::uint8_t>(value>>(byte*8));
        };
        std::string magic="CAISSAN3";std::copy(magic.begin(),magic.end(),bytes.begin());
        const std::array<std::uint32_t,8> fields{3,1,feature_count,transformer_width,dense1_width,dense2_width,1024,2047};
        for(std::size_t i=0;i<fields.size();++i)put(8+i*4,fields[i]);
        std::fill(bytes.begin()+40,bytes.begin()+104,'0');
        put(104,static_cast<std::uint32_t>(payload));put(108,0);put(116,1);
        put(112,crc32(std::span(bytes).subspan(120)));
        std::ofstream output(path,std::ios::binary);
        output.write(reinterpret_cast<const char*>(bytes.data()),static_cast<std::streamsize>(bytes.size()));
        output.close();
        check(static_cast<bool>(output),"synthetic bound control could not be saved");
        return Network::load(path);
    }
};
}
int main(int argc,char** argv) {
    try {
        TemporaryNetwork temporary;
        std::vector<std::shared_ptr<const Network>> networks{temporary.make()};
        if(argc==2)networks.push_back(Network::load(argv[1]));
        const std::array<const char*,8> fens{
            "8/8/8/3p4/3P1k2/8/4K3/8 w - - 0 1",
            "7k/8/3p4/4P3/4K3/8/8/8 w - - 0 1",
            "6k1/5p2/4P3/8/8/8/5K2/8 w - - 0 1",
            "8/8/8/6k1/8/2n5/2P2K2/8 w - - 0 1",
            "7k/8/5K2/6P1/8/8/8/8 w - - 0 1",
            "k7/8/8/2p5/2R5/8/8/7K w - - 0 1",
            "7k/8/4K3/8/8/8/1P6/8 w - - 99 1",
            "7k/8/4K3/8/8/8/1P6/8 w - - 149 1"};
        std::uint64_t shortcuts=0,comparisons=0;
        for(auto& network:networks)for(int weight:{10,100})for(auto fen:fens) {
            auto position=Position::from_fen(fen);
            int expected=full_tree(position,*network,weight,3,0);
            for(bool bounded:{false,true}) {
                SearchOptions options;
                options.network=network;options.neural_weight=weight;options.neural_bounds=bounded;
                options.table=false;options.null_move=false;options.lmr=false;options.extensions=false;
                options.futility=false;options.history=false;options.aspiration=false;
                Search engine(std::make_shared<TranspositionTable>(1));
                Limits limits;limits.depth=3;
                auto result=engine.run(position,limits,options,std::make_shared<SearchControl>());
                check(result.score==expected,"certified neural search differs from independent full tree");
                shortcuts+=result.info.stats.neural_bound_cutoffs;
                ++comparisons;
            }
        }
        check(shortcuts>0,"synthetic control did not exercise any certified cutoff");
        auto position=Position::start();auto acc=networks[0]->refresh(position);
        position.make(position.legal()[0]);bool rejected=false;
        try{(void)networks[0]->evaluate_at_least(position,acc,-infinity);}catch(const std::logic_error&){rejected=true;}
        check(rejected,"certified shortcut accepted a stale accumulator");
        std::cout<<"{\"status\":\"passed\",\"full_tree_comparisons\":"<<comparisons
                 <<",\"reference_qnodes\":"<<visited<<",\"certified_cutoffs\":"<<shortcuts<<"}\n";
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
