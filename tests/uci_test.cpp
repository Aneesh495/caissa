#include "caissa/uci.hpp"
#include <sstream>
#include <iostream>
#include <stdexcept>
int main(){try {
    std::istringstream input("uci\nsetoption name Hash value 1\nposition startpos moves e2e4 e7e5\ngo ponder depth 1\nponderhit\nisready\nstop\nquit\n");
    std::ostringstream output;int status=caissa::uci_loop(input,output);auto text=output.str();
    if(status!=0||text.find("uciok")==std::string::npos||text.find("readyok")==std::string::npos||text.find("bestmove ")==std::string::npos)throw std::runtime_error("bounded memory-stream protocol path failed");
    auto first=text.find("bestmove ");if(text.find("bestmove ",first+1)!=std::string::npos)throw std::runtime_error("duplicate bestmove");
    std::istringstream malformed(std::string(9000,'x')+"\nisready\nquit\n");std::ostringstream errors;
    if(caissa::uci_loop(malformed,errors)!=0||errors.str().find("exceeds 8192")==std::string::npos||errors.str().find("readyok")==std::string::npos)throw std::runtime_error("oversized command recovery failed");
    std::cout<<"owned protocol lifecycle, early ponder hit and oversized recovery passed\n";
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
