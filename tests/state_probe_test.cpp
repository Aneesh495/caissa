#include "caissa/state_probe.hpp"
#include <iostream>
#include <sstream>
#include <stdexcept>
using namespace caissa;
namespace {
void require(bool condition,const char* text){if(!condition)throw std::runtime_error(text);}
std::vector<std::string> run(const Network& network,const std::string& commands) {
    std::istringstream input(commands);std::ostringstream output;
    require(state_probe(input,output,network)==0,"state diagnostic transport failed");
    std::istringstream rows(output.str());std::vector<std::string> result;
    for(std::string line;std::getline(rows,line);)result.push_back(std::move(line));
    return result;
}
}
int main(int argc,char** argv){try {
    if(argc!=2)throw InputError("state_probe_test network");auto network=Network::load(argv[1]);
    unsigned restores=0;
    for(auto [fen,move]:{
        std::pair{std::string(start_fen),"e2e4"},
        std::pair{std::string("4k3/8/8/5pP1/8/8/8/4K3 w - f6 0 1"),"g5f6"},
        std::pair{std::string("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1"),"a7b8n"},
        std::pair{std::string("4k3/P7/8/8/8/8/8/4K3 w - - 0 1"),"a7a8q"},
        std::pair{std::string("960|4k3/8/8/8/8/8/8/5KR1 w G - 0 1"),"f1g1"},
        std::pair{std::string("960|4k3/8/8/8/8/8/8/6KR w H - 0 1"),"g1h1"},
        std::pair{std::string("960|4k3/8/8/8/8/8/8/1RK5 w B - 0 1"),"c1b1"}}) {
        std::string commands="reset "+fen+"\n";
        for(int i=0;i<32;++i)commands+="move "+std::string(move)+"\nundo\n";
        auto rows=run(*network,commands);require(rows.size()==65,"state diagnostic response count differs");
        for(std::size_t i=1;i<rows.size();++i) {
            require(rows[i].find("\"full_refresh_equal\":true")!=std::string::npos,"state diagnostic lost accumulator refresh equality");
            require(rows[i].find("\"coherent\":true")!=std::string::npos,"state diagnostic lost board coherence");
            if(i%2==0){require(rows[i]==rows[0],"move/undo did not restore the complete observed state");++restores;}
        }
    }
    auto nulls=run(*network,"state\nnull\nnull\nundo\nundo\n");
    require(nulls.size()==5&&nulls[0]==nulls[4]&&nulls[1]==nulls[3],"nested null restoration differs");
    require(nulls[1].find("\"synthetic_depth\":1")!=std::string::npos&&nulls[2].find("\"synthetic_depth\":2")!=std::string::npos,"nested null depth not exposed");
    auto errors=run(*network,"state\nundo\nmove a1a8\nabsent\n"+std::string(1025,'x')+"\nstate\n");
    require(errors.size()==6&&errors[0]==errors[5],"rejected diagnostic commands changed state");
    for(std::size_t i=1;i<5;++i)require(errors[i].starts_with("{\"error\":"),"malformed diagnostic command was accepted");
    std::cout<<"{\"status\":\"passed\",\"exact_restores\":"<<restores<<",\"nested_nulls\":2,\"rejections\":4}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
