#include "caissa/serialization.hpp"
#include <ostream>
namespace caissa {
std::string json_quote(std::string_view text) {
    constexpr char hex[]="0123456789abcdef";std::string out="\"";
    for(char raw:text) {
        auto c=static_cast<unsigned char>(raw);
        if(c=='"'||c=='\\'){out+='\\';out+=static_cast<char>(c);}
        else if(c=='\n')out+="\\n";else if(c=='\r')out+="\\r";else if(c=='\t')out+="\\t";
        else if(c<32){out+="\\u00";out+=hex[c>>4];out+=hex[c&15];}
        else out+=static_cast<char>(c);
    }
    out+='"';return out;
}
void write_game_json(std::ostream& out,const Game& game) {
    out<<"{\"initial\":"<<json_quote(game.initial.fen())<<",\"chess960\":"<<(game.initial.chess960()?"true":"false")<<",\"result\":"<<json_quote(game.result)<<",\"pgn\":"<<json_quote(game.pgn())<<",\"tags\":{";
    bool first=true;for(auto& [k,v]:game.tags){if(!first)out<<',';first=false;out<<json_quote(k)<<':'<<json_quote(v);}out<<"},\"nodes\":[";
    for(std::size_t i=0;i<game.nodes.size();++i) {
        if(i)out<<',';auto& node=game.nodes[i];auto p=game.position_at(i);
        out<<"{\"id\":"<<i<<",\"parent\":"<<node.parent<<",\"fen\":"<<json_quote(p.fen())<<",\"san\":";
        auto before=i?game.position_at(node.parent):game.initial;
        out<<json_quote(i?san(before,node.move):"")<<",\"uci\":"<<json_quote(i?before.uci(node.move):"")<<",\"comment\":"<<json_quote(node.comment)<<",\"children\":[";
        for(std::size_t j=0;j<node.children.size();++j){if(j)out<<',';out<<node.children[j];}out<<"]}";
    }
    out<<"]}\n";
}
}
