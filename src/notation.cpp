#include "caissa/notation.hpp"
#include <algorithm>
#include <charconv>
#include <cctype>
#include <sstream>
#include <functional>
namespace caissa {
std::string san(Position& p,Move m) {
    auto legal=p.legal();if(std::find(legal.begin(),legal.end(),m)==legal.end())throw InputError("SAN requested for illegal move");
    std::string text;
    if(m.flag==MoveFlag::castle)text=file(m.to)>file(m.from)?"O-O":"O-O-O";
    else {
        auto k=kind(p.at(m.from));bool capture=m.flag==MoveFlag::en_passant||p.at(m.to);
        if(k!=Kind::pawn) {
            text+=std::string_view(" PNBRQK")[static_cast<std::size_t>(k)];bool conflict=false,same_file=false,same_rank=false;
            for(auto other:legal)if(other.from!=m.from&&other.to==m.to&&kind(p.at(other.from))==k) {
                conflict=true;same_file|=file(other.from)==file(m.from);same_rank|=rank(other.from)==rank(m.from);
            }
            if(conflict) {if(!same_file)text+=static_cast<char>('a'+file(m.from));else if(!same_rank)text+=static_cast<char>('1'+rank(m.from));else text+=square_name(m.from);}
        }else if(capture)text+=static_cast<char>('a'+file(m.from));
        if(capture)text+='x';text+=square_name(m.to);
        if(m.promotion!=Kind::none){text+='=';text+=std::string_view(" PNBRQK")[static_cast<std::size_t>(m.promotion)];}
    }
    auto u=p.make(m);if(p.in_check(p.side()))text+=p.legal().empty()?'#':'+';p.unmake(u);return text;
}
namespace {
std::string normalize(std::string_view value) {
    std::string s(value);for(char& c:s)if(c=='0')c='O';
    while(!s.empty()&&(s.back()=='!'||s.back()=='?'||s.back()=='+'||s.back()=='#'))s.pop_back();return s;
}
enum class TokenKind {symbol,number,comment,nag,open,close,tag,end};
struct Token {TokenKind kind;std::string value;std::size_t offset;};
class Lexer {
public:
    explicit Lexer(std::string_view source):source_(source){}
    Token next() {
        while(offset_<source_.size()&&std::isspace(static_cast<unsigned char>(source_[offset_])))++offset_;
        if(offset_==source_.size())return {TokenKind::end,"",offset_};
        std::size_t begin=offset_;char c=source_[offset_++];
        if(c=='(')return {TokenKind::open,"",begin};if(c==')')return {TokenKind::close,"",begin};
        if(c=='{'||c==';') {
            auto end=source_.find(c=='{'?'}':'\n',offset_);
            if(end==std::string_view::npos){if(c=='{')fail("unclosed comment",begin);end=source_.size();}
            if(end-offset_>4096)fail("comment exceeds 4096 bytes",begin);
            std::string text(source_.substr(offset_,end-offset_));offset_=std::min(end+1,source_.size());return {TokenKind::comment,text,begin};
        }
        if(c=='[') {
            bool quote=false,escape=false;
            while(offset_<source_.size()) {
                char v=source_[offset_++];if(escape){escape=false;continue;}if(v=='\\'&&quote){escape=true;continue;}if(v=='"')quote=!quote;
                if(v==']'&&!quote)return {TokenKind::tag,std::string(source_.substr(begin+1,offset_-begin-2)),begin};
                if(offset_-begin>4096)fail("oversized tag",begin);
            }
            fail("unclosed tag",begin);
        }
        if(c=='$') {
            while(offset_<source_.size()&&std::isdigit(static_cast<unsigned char>(source_[offset_])))++offset_;
            return {TokenKind::nag,std::string(source_.substr(begin+1,offset_-begin-1)),begin};
        }
        for(auto result:{std::string_view("1/2-1/2"),std::string_view("1-0"),std::string_view("0-1"),std::string_view("*")})
            if(source_.substr(begin).starts_with(result)){offset_=begin+result.size();return {TokenKind::symbol,std::string(result),begin};}
        if(std::isdigit(static_cast<unsigned char>(c))) {
            while(offset_<source_.size()&&std::isdigit(static_cast<unsigned char>(source_[offset_])))++offset_;
            if(offset_<source_.size()&&source_[offset_]=='.') {
                while(offset_<source_.size()&&source_[offset_]=='.')++offset_;
                return {TokenKind::number,std::string(source_.substr(begin,offset_-begin)),begin};
            }
        }
        while(offset_<source_.size()&&!std::isspace(static_cast<unsigned char>(source_[offset_]))&&std::string_view("(){}[];$").find(source_[offset_])==std::string_view::npos)++offset_;
        if(offset_-begin>32)fail("oversized movetext token",begin);
        return {TokenKind::symbol,std::string(source_.substr(begin,offset_-begin)),begin};
    }
    [[noreturn]] static void fail(const std::string& reason,std::size_t offset){throw InputError("PGN byte "+std::to_string(offset)+": "+reason);}
private:
    std::string_view source_;std::size_t offset_=0;
};
std::pair<std::string,std::string> parse_tag(const Token& token) {
    auto& s=token.value;std::size_t i=0;
    while(i<s.size()&&std::isspace(static_cast<unsigned char>(s[i])))++i;std::size_t begin=i;
    while(i<s.size()&&(std::isalnum(static_cast<unsigned char>(s[i]))||s[i]=='_'))++i;
    if(begin==i)Lexer::fail("invalid tag name",token.offset);std::string key=s.substr(begin,i-begin);
    while(i<s.size()&&std::isspace(static_cast<unsigned char>(s[i])))++i;
    if(i>=s.size()||s[i++]!='"')Lexer::fail("tag value requires quotes",token.offset);
    std::string value;bool closed=false;
    for(;i<s.size();++i){char c=s[i];if(c=='"'){++i;closed=true;break;}if(c=='\\'){if(++i==s.size())Lexer::fail("truncated tag escape",token.offset);c=s[i];if(c!='"'&&c!='\\')Lexer::fail("invalid tag escape",token.offset);}value+=c;}
    while(i<s.size()&&std::isspace(static_cast<unsigned char>(s[i])))++i;
    if(!closed||i!=s.size())Lexer::fail("invalid tag trailer",token.offset);return {key,value};
}
std::string quote(std::string_view s){std::string result;for(char c:s){if(c=='"'||c=='\\')result+='\\';if(c=='\n'||c=='\r')result+=' ';else result+=c;}return result;}
}
std::optional<Move> parse_san(Position& p,std::string_view token) {
    auto wanted=normalize(token);std::optional<Move> found;
    for(auto m:p.legal())if(normalize(san(p,m))==wanted){if(found)return std::nullopt;found=m;}return found;
}
std::size_t Game::append(std::size_t parent,Move move) {
    if(parent>=nodes.size()||nodes.size()>=8192)throw InputError("variation node limit exceeded");
    auto p=position_at(parent);auto moves=p.legal();if(std::find(moves.begin(),moves.end(),move)==moves.end())throw InputError("variation move illegal at parent");
    for(auto child:nodes[parent].children)if(nodes[child].move==move)return child;
    std::size_t id=nodes.size();nodes.push_back({parent,move,{},{},{}});nodes[parent].children.push_back(id);return id;
}
Position Game::position_at(std::size_t node)const {
    if(node>=nodes.size())throw InputError("variation node absent");std::vector<Move> path;
    while(node){if(path.size()>=1024)throw InputError("variation path exceeds 1024 plies");path.push_back(nodes[node].move);node=nodes[node].parent;}
    auto p=initial;for(auto it=path.rbegin();it!=path.rend();++it)p.make(*it);return p;
}
Game Game::parse(std::string_view source) {
    if(source.size()>1024*1024)throw InputError("PGN exceeds 1 MiB");Game game;Lexer lexer(source);Position p=game.initial;
    std::size_t current=0;std::vector<std::pair<std::size_t,Position>> stack;bool started=false,ended=false;
    for(;;) {
        auto t=lexer.next();if(t.kind==TokenKind::end)break;
        if(t.kind==TokenKind::tag) {
            if(started)Lexer::fail("tag after movetext",t.offset);auto [key,value]=parse_tag(t);
            if(game.tags.contains(key))Lexer::fail("duplicate tag",t.offset);game.tags.emplace(std::move(key),std::move(value));
            bool variant=game.tags.contains("Variant")&&(game.tags.at("Variant")=="Chess960"||game.tags.at("Variant")=="Fischerandom");
            if(game.tags.contains("FEN"))game.initial=Position::from_fen(game.tags.at("FEN"),variant);else game.initial=Position::from_fen(start_fen,variant);p=game.initial;continue;
        }
        if(t.kind==TokenKind::comment){if(!game.nodes[current].comment.empty())game.nodes[current].comment+=' ';game.nodes[current].comment+=t.value;continue;}
        if(t.kind==TokenKind::number)continue;
        if(t.kind==TokenKind::nag){int n=-1;auto [end,ec]=std::from_chars(t.value.data(),t.value.data()+t.value.size(),n);if(ec!=std::errc{}||end!=t.value.data()+t.value.size()||n<0||n>255)Lexer::fail("invalid annotation",t.offset);game.nodes[current].nags.push_back(n);continue;}
        if(ended)Lexer::fail("movetext after result",t.offset);
        if(t.kind==TokenKind::open){if(!current||stack.size()>=64)Lexer::fail("invalid or excessive variation nesting",t.offset);stack.emplace_back(current,p);current=game.nodes[current].parent;p=game.position_at(current);continue;}
        if(t.kind==TokenKind::close){if(stack.empty())Lexer::fail("unmatched variation close",t.offset);current=stack.back().first;p=stack.back().second;stack.pop_back();continue;}
        if(t.value=="1-0"||t.value=="0-1"||t.value=="1/2-1/2"||t.value=="*") {
            if(!stack.empty())Lexer::fail("result inside variation unsupported",t.offset);game.result=t.value;ended=true;continue;
        }
        if(t.value=="e.p.")continue;started=true;auto move=parse_san(p,t.value);if(!move)Lexer::fail("illegal or ambiguous SAN "+t.value,t.offset);
        current=game.append(current,*move);p.make(*move);
    }
    if(!stack.empty())throw InputError("PGN has unclosed variation");
    if(game.tags.contains("Result")&&game.tags.at("Result")!=game.result)throw InputError("PGN result tag disagrees with movetext");
    return game;
}
std::string Game::pgn()const {
    std::ostringstream out;auto headers=tags;headers["Result"]=result;
    if(initial.fen()!=start_fen){headers["SetUp"]="1";headers["FEN"]=initial.fen();}
    if(initial.chess960())headers["Variant"]="Chess960";
    for(auto& [key,value]:headers)out<<'['<<key<<" \""<<quote(value)<<"\"]\n";out<<'\n';
    std::function<void(Position,std::size_t,bool,int)> branch;
    branch=[&](Position p,std::size_t child,bool first,int nesting) {
        if(nesting>64)throw InputError("variation nesting exceeds limit");
        for(;;) {
            const auto& node=nodes[child];
            if(p.side()==Color::white)out<<p.fullmove()<<". ";else if(first)out<<p.fullmove()<<"... ";
            out<<san(p,node.move)<<' ';for(auto n:node.nags)out<<'$'<<n<<' ';
            if(!node.comment.empty()){auto text=node.comment;std::replace(text.begin(),text.end(),'}',']');out<<'{'<<text<<"} ";}
            // Sibling alternatives belong to the position before this move.
            for(auto sibling:nodes[node.parent].children)if(sibling!=child&&nodes[node.parent].children[0]==child){out<<"( ";branch(p,sibling,true,nesting+1);out<<") ";}
            p.make(node.move);if(node.children.empty())break;child=node.children[0];first=false;
        }
    };
    if(!nodes[0].children.empty())branch(initial,nodes[0].children[0],true,0);
    out<<result<<'\n';return out.str();
}
}
