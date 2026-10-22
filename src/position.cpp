#include "caissa/position.hpp"
#include <algorithm>
#include <charconv>
#include <cctype>
#include <sstream>
namespace caissa {
namespace {
Key mix(Key v) {
    v += 0x9e3779b97f4a7c15ULL;
    v = (v^(v>>30))*0xbf58476d1ce4e5b9ULL;
    v = (v^(v>>27))*0x94d049bb133111ebULL;
    return v^(v>>31);
}
Piece decode(char c) {
    constexpr std::string_view names=" PNBRQK";
    auto k=names.find(static_cast<char>(std::toupper(static_cast<unsigned char>(c))));
    if(k==std::string_view::npos || k==0) throw InputError("unknown FEN piece");
    return piece(std::isupper(static_cast<unsigned char>(c))?Color::white:Color::black,static_cast<Kind>(k));
}
char encode(Piece p) {
    char c=std::string_view(" PNBRQK")[static_cast<std::size_t>(kind(p))];
    return color(p)==Color::white?c:static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
}
std::uint32_t counter(const std::string& s, bool positive) {
    std::uint32_t n=0;
    auto [ptr,ec]=std::from_chars(s.data(),s.data()+s.size(),n);
    if(ec!=std::errc{}||ptr!=s.data()+s.size()||n>1000000||(positive&&n==0)) throw InputError("invalid FEN clock");
    return n;
}
}
void Position::put(Square s, Piece p) {
    auto old=board_[s];
    if(old) {
        key_^=mix(static_cast<Key>(old)*64+s);
        auto c=static_cast<std::size_t>(index(color(old)));
        pieces_[c][static_cast<std::size_t>(kind(old))]&=~bit(s);
        colors_[c]&=~bit(s);
    }
    board_[s]=p;
    if(p) {
        key_^=mix(static_cast<Key>(p)*64+s);
        auto c=static_cast<std::size_t>(index(color(p)));
        pieces_[c][static_cast<std::size_t>(kind(p))]|=bit(s);
        colors_[c]|=bit(s);
    }
}
Position Position::from_fen(std::string_view fen, bool chess960) {
    if(fen.size()>256) throw InputError("FEN exceeds 256 bytes");
    std::istringstream in{std::string(fen)};
    std::string placement,turn,rights,ep,half,full,trailing;
    if(!(in>>placement>>turn>>rights>>ep>>half>>full)||(in>>trailing)) throw InputError("FEN needs exactly six fields");
    Position p; p.chess960_=chess960;
    int f=0,r=7;
    for(char c:placement) {
        if(c=='/') {
            if(f!=8||r==0) throw InputError("invalid FEN rank");
            f=0;--r;
        } else if(c>='1'&&c<='8') { f+=c-'0';if(f>8) throw InputError("FEN rank overflow"); }
        else { if(f>=8||r<0) throw InputError("FEN placement overflow"); p.put(square(f++,r),decode(c)); }
    }
    if(f!=8||r!=0) throw InputError("FEN must contain eight full ranks");
    if(turn!="w"&&turn!="b") throw InputError("invalid side to move");
    p.side_=turn=="w"?Color::white:Color::black;
    for(Color c:{Color::white,Color::black}) {
        if(std::popcount(p.pieces(c,Kind::king))!=1) throw InputError("exactly one king per color required");
        if(std::popcount(p.pieces(c,Kind::pawn))>8||std::popcount(p.occupied(c))>16) throw InputError("piece count exceeds reachable maximum");
        if(p.pieces(c,Kind::pawn)&0xff000000000000ffULL) throw InputError("pawn on promotion rank");
    }
    if(attacks::king(p.king(Color::white))&p.pieces(Color::black,Kind::king)) throw InputError("adjacent kings");
    if(rights!="-") for(char c:rights) {
        Color side=std::isupper(static_cast<unsigned char>(c))?Color::white:Color::black;
        int home=side==Color::white?0:7;
        if(rank(p.king(side))!=home) throw InputError("castling king off home rank");
        char upper=static_cast<char>(std::toupper(static_cast<unsigned char>(c)));
        Square rook=no_square;
        if(upper=='K'||upper=='Q') {
            if(!chess960) rook=square(upper=='K'?7:0,home);
            else {
                Bitboard rooks=p.pieces(side,Kind::rook)&(Bitboard{0xff}<<(home*8));
                while(rooks) {
                    auto s=pop_lsb(rooks);
                    if(upper=='K'&&file(s)>file(p.king(side))) rook=s;
                    if(upper=='Q'&&file(s)<file(p.king(side))&&rook==no_square) rook=s;
                }
            }
        } else if(chess960&&upper>='A'&&upper<='H') rook=square(upper-'A',home);
        else throw InputError("invalid castling field");
        if(rook>=64||p.at(rook)!=piece(side,Kind::rook)||rook==p.king(side)) throw InputError("castling rook absent");
        if(!chess960&&file(p.king(side))!=4) throw InputError("standard castling king not on e-file");
        int wing=file(rook)>file(p.king(side))?1:0;
        auto& right=p.castling_[static_cast<std::size_t>(index(side))][static_cast<std::size_t>(wing)];
        if(right!=no_square) throw InputError("duplicate castling right");
        right=rook;
    }
    if(ep!="-") {
        auto s=parse_square(ep);
        if(!s||rank(*s)!=(p.side_==Color::white?5:2)||p.at(*s)) throw InputError("invalid en passant target");
        int step=p.side_==Color::white?8:-8;
        if(p.at(static_cast<Square>(*s-step))!=piece(opposite(p.side_),Kind::pawn)||p.at(static_cast<Square>(*s+step)))
            throw InputError("en passant predecessor inconsistent");
        p.ep_=*s;
    }
    p.halfmove_=counter(half,false);p.fullmove_=counter(full,true);
    if(p.ep_!=no_square&&p.halfmove_!=0)throw InputError("en passant requires a zero halfmove clock");
    if(p.in_check(opposite(p.side_))) throw InputError("side that just moved is in check");
    p.key_=p.recompute_key();
    p.history_.push_back(p.repetition_key());
    return p;
}
std::string Position::fen() const {
    std::string out;
    for(int r=7;r>=0;--r) {
        int empty=0;
        for(int f=0;f<8;++f) {
            auto p=at(square(f,r));
            if(!p) ++empty;
            else { if(empty) out+=static_cast<char>('0'+empty);empty=0;out+=encode(p); }
        }
        if(empty) out+=static_cast<char>('0'+empty);
        if(r) out+='/';
    }
    out+=side_==Color::white?" w ":" b ";
    std::string rights;
    for(Color c:{Color::white,Color::black}) for(int wing:{1,0}) {
        auto s=rook_right(c,wing); if(s==no_square) continue;
        char ch=chess960_?static_cast<char>('A'+file(s)):(wing==1?'K':'Q');
        if(c==Color::black) ch=static_cast<char>(std::tolower(static_cast<unsigned char>(ch)));
        rights+=ch;
    }
    out+=rights.empty()?"-":rights;
    out+=' ';out+=square_name(ep_);out+=' ';out+=std::to_string(halfmove_);out+=' ';out+=std::to_string(fullmove_);
    return out;
}
Key Position::metadata_key() const {
    Key h=side_==Color::black?mix(10000):0;
    for(Color c:{Color::white,Color::black}) for(int w=0;w<2;++w) {
        auto s=rook_right(c,w);if(s<64) h^=mix(11000+static_cast<Key>(index(c)*128+w*64+s));
    }
    if(ep_<64) h^=mix(12000+ep_);
    return h;
}
Key Position::recompute_key() const {
    Key h=metadata_key();
    for(Square s=0;s<64;++s) if(at(s)) h^=mix(static_cast<Key>(at(s))*64+s);
    return h;
}
Key Position::repetition_key() const {
    if(ep_==no_square) return key_;
    auto candidates=attacks::pawn(opposite(side_),ep_)&pieces(side_,Kind::pawn);
    while(candidates) {
        auto from=pop_lsb(candidates);
        Position copy=*this;
        auto captured=static_cast<Square>(static_cast<int>(ep_)+(side_==Color::white?-8:8));
        copy.put(from,0);copy.put(captured,0);copy.put(ep_,piece(side_,Kind::pawn));
        if(!copy.in_check(side_)) return key_;
    }
    return key_^mix(12000+ep_);
}
Key Position::search_key() const {
    Key context=mix(halfmove_+20000);
    if(synthetic_depth_)context^=mix(30000+static_cast<Key>(synthetic_depth_));
    auto count=std::min(history_.size(),static_cast<std::size_t>(halfmove_)+1);
    for(std::size_t i=history_.size()-count;i<history_.size();++i) context=mix(context^history_[i]);
    return key_^context;
}
bool Position::coherent() const {
    std::array<std::array<Bitboard,7>,2> bb{};
    std::array<Bitboard,2> colors{};
    for(Square s=0;s<64;++s) if(at(s)) {
        auto c=static_cast<std::size_t>(index(color(at(s))));bb[c][static_cast<std::size_t>(kind(at(s)))]|=bit(s);colors[c]|=bit(s);
    }
    return bb==pieces_&&colors==colors_&&key_==recompute_key();
}
}
