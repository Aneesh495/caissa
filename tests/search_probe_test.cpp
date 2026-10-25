#include "caissa/search_probe.hpp"
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <vector>
using namespace caissa;
void require(bool condition,const char* reason){if(!condition)throw std::runtime_error(reason);}
int main(){try {
    std::istringstream input("clear\nstore 000000000000002a 1 18 29993 12 8 2 4 end\nprobe 000000000000002a 7\nhint 0000000000000054 1 18 8\nprobe 0000000000000054 0\nclear\nprobe 000000000000002a 0\nsearch 1 3 0 10000 0|1r5k/8/8/8/8/8/8/K7 w - - 99 50|\nsearch 7 0 0 1 0|garbage|\nstore 000000000000002a 1 18 31000 0 1 1 0 end\nprobe 000000000000002a 0\n"+std::string(1025,'x')+"\nclear\n");
    std::ostringstream output;require(search_probe(input,output)==0,"search probe channel failed");
    std::vector<std::string> rows;std::istringstream text(output.str());for(std::string line;std::getline(text,line);)rows.push_back(line);
    require(rows.size()==13,"search probe response inventory differs");
    require(rows[1].find("\"stored_score\":29997")!=std::string::npos&&rows[1].find("\"bound\":2")!=std::string::npos,"actual table store absent");
    require(rows[2].find("\"score\":29990")!=std::string::npos,"actual table mate normalization absent");
    require(rows[3].find("\"entry\":null")!=std::string::npos&&rows[4].find("\"hint\":2305")!=std::string::npos,"hint became a score entry");
    require(rows[6].find("\"entry\":null")!=std::string::npos&&rows[10].find("\"entry\":null")!=std::string::npos,"clear or rejected table write changed identity");
    require(rows[7].find("\"score\":0")!=std::string::npos&&rows[7].find("\"bestmove\":\"a1a2\"")!=std::string::npos,"probe did not execute the actual intended-claim search");
    for(auto i:{8,9,11})require(rows[static_cast<std::size_t>(i)].starts_with("{\"error\":"),"malformed search-probe request accepted");
    std::cout<<"{\"status\":\"passed\",\"requests\":13,\"rejected\":3,\"scope\":\"Real search/table/hint transport\"}\n";
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
